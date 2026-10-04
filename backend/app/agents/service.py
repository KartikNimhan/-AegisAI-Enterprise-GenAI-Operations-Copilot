"""Agent orchestration: build initial state, run the graph (bounded by a
wall-clock timeout), extract the final answer/sources/tool usage, persist
the conversation turn.

Mirrors `app.rag.service.RAGService`'s shape and conversation handling
(`_get_or_create_conversation`, one commit per request via
`app.db.session.get_session`'s ambient commit/rollback) — intentionally
duplicated rather than shared, the same small, deliberate duplication
`RAGService` itself accepted relative to `ChatService` (see ADR 007 and
ADR 008, "Conversation integration").
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import Depends
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.exceptions import AgentTimeoutError
from app.agents.graph import MAX_STEPS_RESPONSE, build_agent_graph
from app.agents.messages import final_answer_text, history_to_langchain_messages
from app.agents.prompts import AEGIS_AGENT_SYSTEM_PROMPT
from app.agents.schemas import (
    STATUS_COMPLETED,
    STATUS_MAX_STEPS_EXCEEDED,
    AgentRunResult,
    AgentSource,
    AgentState,
    AgentStreamEvent,
    ToolUsageSummary,
)
from app.agents.tools.registry import build_tool_registry
from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.message_repository import MessageRepository
from app.dependencies import DBSessionDep
from app.domain.enums.message_role import MessageRole
from app.domain.models.conversation import Conversation
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.schemas import ModelRole
from app.rag.retrieval.service import RetrievalService, get_retrieval_service

logger = structlog.get_logger(__name__)

_TITLE_MAX_LENGTH = 80


class AgentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        gateway: LLMGateway,
        conversations: ConversationRepository,
        messages: MessageRepository,
        documents: DocumentRepository,
        retrieval: RetrievalService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._conversations = conversations
        self._messages = messages
        tool_registry = build_tool_registry(documents=documents, retrieval=retrieval)
        self._graph = build_agent_graph(
            gateway=gateway, tool_registry=tool_registry, settings=settings
        )

    async def _prepare_run(
        self, *, conversation_id: uuid.UUID | None, message: str
    ) -> tuple[Conversation, AgentState]:
        conversation = await self._get_or_create_conversation(conversation_id, message)
        history = await self._messages.list_by_conversation(conversation.id)

        initial_messages: list[BaseMessage] = [
            SystemMessage(content=AEGIS_AGENT_SYSTEM_PROMPT.text),
            *history_to_langchain_messages(history),
            HumanMessage(content=message),
        ]

        await self._messages.add(
            conversation_id=conversation.id, role=MessageRole.USER, content=message
        )

        initial_state: AgentState = {
            "messages": initial_messages,
            "step_count": 0,
            "tool_call_count": 0,
            "tool_calls_by_name": {},
            "status": STATUS_COMPLETED,
        }
        return conversation, initial_state

    async def run(
        self,
        *,
        conversation_id: uuid.UUID | None,
        message: str,
        model_role: ModelRole = ModelRole.PRIMARY,
    ) -> AgentRunResult:
        run_id = uuid.uuid4()
        conversation, initial_state = await self._prepare_run(
            conversation_id=conversation_id, message=message
        )

        logger.info("agent.started", run_id=str(run_id), conversation_id=str(conversation.id))
        start = time.perf_counter()
        recursion_limit = self._settings.agent_max_steps * 2 + 10

        try:
            final_state = await asyncio.wait_for(
                self._graph.ainvoke(initial_state, config={"recursion_limit": recursion_limit}),
                timeout=self._settings.agent_timeout_seconds,
            )
        except TimeoutError as exc:
            logger.warning("agent.failed", run_id=str(run_id), reason="timeout")
            raise AgentTimeoutError(
                f"Agent run exceeded {self._settings.agent_timeout_seconds}s"
            ) from exc
        except GraphRecursionError:
            # Should not normally trigger — should_continue already stops
            # the graph before this point — but is a real backstop against
            # a future bug in the step/tool-call accounting above.
            logger.error("agent.recursion_limit_hit", run_id=str(run_id))
            final_state = {
                "messages": [*initial_state["messages"], AIMessage(content=MAX_STEPS_RESPONSE)],
                "step_count": self._settings.agent_max_steps,
                "tool_call_count": 0,
                "tool_calls_by_name": {},
                "status": STATUS_MAX_STEPS_EXCEEDED,
            }
        except Exception:
            logger.error("agent.failed", run_id=str(run_id), conversation_id=str(conversation.id))
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        answer = final_answer_text(final_state["messages"])
        sources = _extract_sources(final_state["messages"])
        tool_usage = _summarize_tool_usage(final_state["messages"])

        await self._messages.add(
            conversation_id=conversation.id, role=MessageRole.ASSISTANT, content=answer
        )
        await self._conversations.touch(conversation)

        logger.info(
            "agent.completed",
            run_id=str(run_id),
            conversation_id=str(conversation.id),
            status=final_state["status"],
            steps=final_state["step_count"],
            tool_calls=final_state["tool_call_count"],
            tool_names=list(final_state["tool_calls_by_name"].keys()),
            duration_ms=duration_ms,
        )

        return AgentRunResult(
            run_id=run_id,
            conversation_id=conversation.id,
            answer=answer,
            status=final_state["status"],
            steps=final_state["step_count"],
            tool_calls=tool_usage,
            sources=sources,
            duration_ms=duration_ms,
        )

    async def run_stream(
        self,
        *,
        conversation_id: uuid.UUID | None,
        message: str,
        model_role: ModelRole = ModelRole.PRIMARY,
    ) -> AsyncIterator[tuple[uuid.UUID, AgentStreamEvent]]:
        """Yields `(conversation_id, event)` pairs — `tool_started` and
        `tool_completed` as each tool call happens, then one `answer_delta`
        carrying the complete final answer, then `completed`.

        Built on `astream(..., stream_mode="updates")`, which yields each
        node's output as it finishes — never an intermediate `AIMessage`'s
        free-text content (the model's reasoning about *why* it's calling a
        tool), only the structured fact that it did, and with what result.
        See ADR 008, "Streaming", for why the final answer itself is
        delivered as one already-complete chunk rather than token-by-token:
        tool-call decisions need the complete structured output from the
        provider, so the agent loop runs non-streaming internally, and the
        answer already exists in full by the time the graph reaches `END`.
        """
        run_id = uuid.uuid4()
        conversation, initial_state = await self._prepare_run(
            conversation_id=conversation_id, message=message
        )
        logger.info("agent.started", run_id=str(run_id), conversation_id=str(conversation.id))
        start = time.perf_counter()
        recursion_limit = self._settings.agent_max_steps * 2 + 10

        all_messages: list[BaseMessage] = list(initial_state["messages"])
        step_count = 0
        tool_call_count = 0
        status = STATUS_COMPLETED
        pending_tool_names: dict[str, str] = {}

        try:
            async with asyncio.timeout(self._settings.agent_timeout_seconds):
                async for update in self._graph.astream(
                    initial_state,
                    config={"recursion_limit": recursion_limit},
                    stream_mode="updates",
                ):
                    for node_name, partial in update.items():
                        partial_messages = partial.get("messages", [])
                        all_messages.extend(partial_messages)
                        step_count = partial.get("step_count", step_count)
                        tool_call_count = partial.get("tool_call_count", tool_call_count)
                        status = partial.get("status", status)

                        if node_name == "agent":
                            for msg in partial_messages:
                                if not (isinstance(msg, AIMessage) and msg.tool_calls):
                                    continue
                                for tool_call in msg.tool_calls:
                                    call_id = tool_call.get("id")
                                    if call_id is None:
                                        continue
                                    pending_tool_names[call_id] = tool_call["name"]
                                    yield (
                                        conversation.id,
                                        AgentStreamEvent(
                                            event="tool_started",
                                            data={"tool_name": tool_call["name"]},
                                        ),
                                    )
                        elif node_name == "tools":
                            for msg in partial_messages:
                                if not isinstance(msg, ToolMessage):
                                    continue
                                payload = _tool_message_payload(msg)
                                yield (
                                    conversation.id,
                                    AgentStreamEvent(
                                        event="tool_completed",
                                        data={
                                            "tool_name": pending_tool_names.get(
                                                msg.tool_call_id, "unknown"
                                            ),
                                            "success": bool(payload.get("success")),
                                        },
                                    ),
                                )
        except TimeoutError as exc:
            logger.warning("agent.failed", run_id=str(run_id), reason="timeout")
            raise AgentTimeoutError(
                f"Agent run exceeded {self._settings.agent_timeout_seconds}s"
            ) from exc
        except GraphRecursionError:
            logger.error("agent.recursion_limit_hit", run_id=str(run_id))
            status = STATUS_MAX_STEPS_EXCEEDED
            all_messages.append(AIMessage(content=MAX_STEPS_RESPONSE))
        except Exception:
            logger.error("agent.failed", run_id=str(run_id), conversation_id=str(conversation.id))
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        answer = final_answer_text(all_messages)

        await self._messages.add(
            conversation_id=conversation.id, role=MessageRole.ASSISTANT, content=answer
        )
        await self._conversations.touch(conversation)

        logger.info(
            "agent.completed",
            run_id=str(run_id),
            conversation_id=str(conversation.id),
            status=status,
            steps=step_count,
            tool_calls=tool_call_count,
            duration_ms=duration_ms,
        )

        yield (conversation.id, AgentStreamEvent(event="answer_delta", data={"delta": answer}))
        yield (conversation.id, AgentStreamEvent(event="completed", data={"status": status}))

    async def _get_or_create_conversation(
        self, conversation_id: uuid.UUID | None, first_message: str
    ) -> Conversation:
        if conversation_id is None:
            return await self._conversations.create(title=_derive_title(first_message))
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            raise NotFoundError(f"Conversation {conversation_id} not found")
        return conversation


def _derive_title(message: str) -> str:
    stripped = message.strip()
    if len(stripped) <= _TITLE_MAX_LENGTH:
        return stripped
    return stripped[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"


def _tool_call_id_to_name(messages: list[BaseMessage]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                call_id = tool_call.get("id")
                if call_id is not None:
                    mapping[call_id] = tool_call["name"]
    return mapping


def _tool_message_payload(message: ToolMessage) -> dict:
    content = message.content if isinstance(message.content, str) else "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def _summarize_tool_usage(messages: list[BaseMessage]) -> list[ToolUsageSummary]:
    """Derives the per-tool summary from the actual `ToolMessage`s in the
    final state — the tool name isn't on `ToolMessage` itself, so this
    pairs each one back to the `AIMessage.tool_calls` entry that requested
    it via `tool_call_id`."""
    id_to_name = _tool_call_id_to_name(messages)
    counts: dict[str, dict[str, int]] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        name = id_to_name.get(msg.tool_call_id, "unknown")
        bucket = counts.setdefault(name, {"call_count": 0, "success_count": 0, "failure_count": 0})
        bucket["call_count"] += 1
        if _tool_message_payload(msg).get("success"):
            bucket["success_count"] += 1
        else:
            bucket["failure_count"] += 1

    return [
        ToolUsageSummary(
            name=name,
            call_count=counts_for_name["call_count"],
            success_count=counts_for_name["success_count"],
            failure_count=counts_for_name["failure_count"],
        )
        for name, counts_for_name in counts.items()
    ]


def _extract_sources(messages: list[BaseMessage]) -> list[AgentSource]:
    """Pulls `search_knowledge_base` results out of the final state's tool
    messages for the API response — deduplicated by chunk id, in
    first-seen order."""
    id_to_name = _tool_call_id_to_name(messages)
    seen_chunk_ids: set[str] = set()
    sources: list[AgentSource] = []

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        if id_to_name.get(msg.tool_call_id) != "search_knowledge_base":
            continue
        payload = _tool_message_payload(msg)
        if not payload.get("success"):
            continue
        for result in (payload.get("data") or {}).get("results", []):
            chunk_id = result.get("chunk_id")
            if chunk_id is None or chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            sources.append(
                AgentSource(
                    chunk_id=uuid.UUID(chunk_id),
                    document_id=uuid.UUID(result["document_id"]),
                    filename=result["filename"],
                    page_number=result.get("page_number"),
                    similarity=result.get("similarity", 0.0),
                )
            )
    return sources


def get_agent_service(
    session: DBSessionDep,
    gateway: Annotated[LLMGateway, Depends(get_llm_gateway)],
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> AgentService:
    settings = get_settings()
    return AgentService(
        session=session,
        settings=settings,
        gateway=gateway,
        conversations=ConversationRepository(session),
        messages=MessageRepository(session),
        documents=DocumentRepository(session),
        retrieval=retrieval,
    )
