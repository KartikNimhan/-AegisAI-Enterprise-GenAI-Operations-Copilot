r"""The agent's LangGraph `StateGraph`.

```
START -> agent -> should_continue? -- tool calls, under both limits --> tools -> agent (loop)
                                   \-- no tool calls ---------------------> END
                                   \-- over AGENT_MAX_STEPS --------------> max_steps -> END
                                   \-- over AGENT_MAX_TOOL_CALLS ---------> max_tool_calls -> END
```

Every edge out of `agent` is decided by `should_continue` — there is no
unconditional loop, and every path reaches `END` in a bounded number of
steps (see ADR 008, "Maximum steps"). The LLM never executes a tool
itself: `agent_node` only ever asks `LLMGateway` for a decision and
appends an `AIMessage`; `tool_node` is the only code that calls
`ToolRegistry.execute`, mirroring the brief's "The LLM must never execute
tools directly."
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Literal

import structlog
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.messages import to_chat_messages
from app.agents.schemas import (
    STATUS_MAX_STEPS_EXCEEDED,
    STATUS_MAX_TOOL_CALLS_EXCEEDED,
    AgentState,
)
from app.agents.tools.base import ToolRegistry
from app.agents.tools.research_delegation import RESEARCH_AGENT_TOOL_NAME
from app.config import Settings
from app.llm.gateway import LLMGateway
from app.llm.schemas import ModelRole, ToolSpec
from app.mcp.client import MCP_TOOL_NAME_PREFIX

logger = structlog.get_logger(__name__)

MAX_STEPS_RESPONSE = (
    "I've reached my step limit for this request without a confident final answer. "
    "Please try rephrasing your question or breaking it into smaller steps."
)
MAX_TOOL_CALLS_RESPONSE = (
    "I've reached my tool-call limit for this request. Please try rephrasing your "
    "question or breaking it into smaller steps."
)

_RouteDecision = Literal["tools", "max_steps", "max_tool_calls", "end"]


def build_agent_graph(
    *,
    gateway: LLMGateway,
    tool_registry: ToolRegistry,
    settings: Settings,
    model_role: ModelRole = ModelRole.PRIMARY,
) -> CompiledStateGraph:
    tool_specs = tool_registry.to_tool_specs()

    agent_node = _make_agent_node(gateway=gateway, tool_specs=tool_specs, model_role=model_role)
    tool_node = _make_tool_node(tool_registry)
    should_continue = _make_should_continue(settings)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("max_steps", _make_stop_node(STATUS_MAX_STEPS_EXCEEDED, MAX_STEPS_RESPONSE))
    graph.add_node(
        "max_tool_calls", _make_stop_node(STATUS_MAX_TOOL_CALLS_EXCEEDED, MAX_TOOL_CALLS_RESPONSE)
    )

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "max_steps": "max_steps",
            "max_tool_calls": "max_tool_calls",
            "end": END,
        },
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("max_steps", END)
    graph.add_edge("max_tool_calls", END)

    return graph.compile()


def _make_agent_node(*, gateway: LLMGateway, tool_specs: list[ToolSpec], model_role: ModelRole):
    async def agent_node(state: AgentState) -> dict:
        chat_messages = to_chat_messages(state["messages"])
        completion = await gateway.chat_completion(
            model_role=model_role, messages=chat_messages, tools=tool_specs
        )
        ai_message = AIMessage(
            content=completion.content,
            tool_calls=[
                {
                    "name": tool_call.name,
                    "args": json.loads(tool_call.arguments),
                    "id": tool_call.id,
                }
                for tool_call in (completion.tool_calls or [])
            ],
        )
        logger.info(
            "agent.step",
            step=state["step_count"] + 1,
            requested_tool_calls=len(completion.tool_calls or []),
            finish_reason=completion.finish_reason,
        )
        return {"messages": [ai_message], "step_count": state["step_count"] + 1}

    return agent_node


def _make_tool_node(tool_registry: ToolRegistry):
    async def tool_node(state: AgentState) -> dict:
        last_message = state["messages"][-1]
        if not isinstance(last_message, AIMessage):
            raise TypeError("tool_node reached with a non-AIMessage as the last message")

        tool_messages: list[ToolMessage] = []
        tool_call_count = state["tool_call_count"]
        tool_calls_by_name = dict(state["tool_calls_by_name"])

        for tool_call in last_message.tool_calls:
            name = tool_call["name"]
            capability = _classify_capability(name)
            logger.info("agent.capability_selected", tool_name=name, capability=capability)

            start = time.perf_counter()
            result = await tool_registry.execute(name, json.dumps(tool_call["args"]))
            duration_ms = round((time.perf_counter() - start) * 1000, 2)

            tool_call_count += 1
            tool_calls_by_name[name] = tool_calls_by_name.get(name, 0) + 1

            logger.info(
                "agent.tool_call",
                tool_name=name,
                capability=capability,
                success=result.success,
                error_code=result.error_code,
                duration_ms=duration_ms,
            )
            tool_messages.append(
                ToolMessage(content=result.to_json(), tool_call_id=tool_call["id"])
            )

        return {
            "messages": tool_messages,
            "tool_call_count": tool_call_count,
            "tool_calls_by_name": tool_calls_by_name,
        }

    return tool_node


def _classify_capability(tool_name: str) -> str:
    """Labels a tool call for observability only — `ToolRegistry.execute`
    itself treats every registered name identically (see its own
    docstring); this distinction never affects dispatch, only what gets
    logged under `agent.capability_selected`/`agent.tool_call`."""
    if tool_name == RESEARCH_AGENT_TOOL_NAME:
        return "a2a"
    if tool_name.startswith(MCP_TOOL_NAME_PREFIX):
        return "mcp"
    return "internal"


def _make_stop_node(status: str, response_text: str):
    async def stop_node(state: AgentState) -> dict:
        logger.warning(
            "agent.limit_reached",
            status=status,
            step_count=state["step_count"],
            tool_call_count=state["tool_call_count"],
        )
        return {"messages": [AIMessage(content=response_text)], "status": status}

    return stop_node


def _make_should_continue(settings: Settings) -> Callable[[AgentState], _RouteDecision]:
    def should_continue(state: AgentState) -> _RouteDecision:
        last_message = state["messages"][-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return "end"
        if state["step_count"] >= settings.agent_max_steps:
            return "max_steps"
        requested = len(last_message.tool_calls)
        if state["tool_call_count"] + requested > settings.agent_max_tool_calls:
            return "max_tool_calls"
        return "tools"

    return should_continue
