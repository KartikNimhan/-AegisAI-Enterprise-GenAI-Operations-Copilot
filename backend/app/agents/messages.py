"""Translates between LangGraph's message world (`langchain_core.messages`)
and this project's own provider-neutral `app.llm.schemas.ChatMessage` —
the same kind of boundary-translation `app.llm.providers.groq` does
between the `groq` SDK and `app.llm.schemas`. `LLMGateway` never sees a
LangChain message type, and the agent graph never sees a raw Groq/provider
object; this module is the only place that converts between the two.
"""

from __future__ import annotations

import json

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.domain.enums.message_role import MessageRole
from app.domain.models.message import Message
from app.llm.schemas import ChatMessage, ChatRole, ToolCall


def to_chat_messages(messages: list[BaseMessage]) -> list[ChatMessage]:
    """Converts the graph's LangChain message list into what
    `LLMGateway.chat_completion` accepts."""
    return [_to_chat_message(message) for message in messages]


def _to_chat_message(message: BaseMessage) -> ChatMessage:
    if isinstance(message, SystemMessage):
        return ChatMessage(role=ChatRole.SYSTEM, content=_text(message))
    if isinstance(message, HumanMessage):
        return ChatMessage(role=ChatRole.USER, content=_text(message))
    if isinstance(message, ToolMessage):
        return ChatMessage(
            role=ChatRole.TOOL, content=_text(message), tool_call_id=message.tool_call_id
        )
    if isinstance(message, AIMessage):
        tool_calls = (
            [
                ToolCall(
                    # LangChain's ToolCall TypedDict declares `id` optional
                    # (`str | None`); every tool call this codebase
                    # produces always sets one (see `app.agents.graph`), so
                    # `None` here would indicate a provider anomaly, not a
                    # normal path — fall back to an empty string rather
                    # than crash on it.
                    id=tc["id"] or "",
                    name=tc["name"],
                    arguments=json.dumps(tc["args"]),
                )
                for tc in message.tool_calls
            ]
            if message.tool_calls
            else None
        )
        return ChatMessage(role=ChatRole.ASSISTANT, content=_text(message), tool_calls=tool_calls)
    raise TypeError(f"Unsupported message type: {type(message).__name__}")


def _text(message: BaseMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else str(content)


def history_to_langchain_messages(history: list[Message]) -> list[BaseMessage]:
    """Converts persisted conversation history (user/assistant turns only
    — see `app.domain.enums.message_role.MessageRole`, which has no TOOL
    value) into the graph's initial message list. Mirrors
    `app.prompts.builder.PromptBuilder`'s identical history-mapping, kept
    separate because it targets LangChain message types, not
    `app.llm.schemas.ChatMessage`.
    """
    converted: list[BaseMessage] = []
    for persisted in history:
        if persisted.role == MessageRole.USER:
            converted.append(HumanMessage(content=persisted.content))
        elif persisted.role == MessageRole.ASSISTANT:
            converted.append(AIMessage(content=persisted.content))
        # MessageRole.SYSTEM rows are never persisted (see Message's own
        # docstring) — nothing to map.
    return converted


def final_answer_text(messages: list[BaseMessage]) -> str:
    """The agent's final answer is, by construction, the content of the
    last `AIMessage` with no pending tool calls — the graph only reaches
    its terminal edge once the model stops requesting tools (see
    `app.agents.graph.should_continue`)."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return _text(message)
    return ""
