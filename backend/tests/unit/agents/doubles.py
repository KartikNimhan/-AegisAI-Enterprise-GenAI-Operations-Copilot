"""Test doubles for agent unit tests.

Not a test module itself (no `test_*` functions). None of these touch a
real database, model, or the real Groq SDK.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.llm.gateway import LLMGateway
from app.llm.schemas import (
    ChatMessage,
    CompletionResponse,
    ModelRole,
    StreamChunk,
    TokenUsage,
    ToolCall,
)


class ScriptedAgentGateway(LLMGateway):
    """Subclasses LLMGateway purely for type compatibility; `__init__`
    deliberately skips real settings/provider setup. `effects` is popped
    one-per-`chat_completion`-call (mirrors `ScriptedProvider` in
    tests/unit/llm/doubles.py) — the agent loop makes multiple calls per
    run, each needing a different scripted response (a tool-call decision,
    then a final answer, etc.), unlike `ScriptedChatGateway`/
    `ScriptedRAGGateway`, which only ever need one.
    """

    def __init__(self, *, effects: list[CompletionResponse | Exception]) -> None:
        self._effects = list(effects)
        self.chat_completion_calls: list[dict[str, Any]] = []

    async def chat_completion(
        self, *, model_role: ModelRole, messages: list[ChatMessage], **kwargs: Any
    ) -> CompletionResponse:
        self.chat_completion_calls.append(
            {"model_role": model_role, "messages": messages, **kwargs}
        )
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    async def stream_chat_completion(
        self, *, model_role: ModelRole, messages: list[ChatMessage], **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError("The agent graph does not stream its internal decisions")
        yield  # pragma: no cover - makes this an async generator for typing

    def model_metadata(self) -> dict[str, str]:
        return {"provider": "fake", "primary": "fake-model"}


def make_tool_call_completion(
    *, tool_name: str, arguments: dict[str, Any], call_id: str | None = None
) -> CompletionResponse:
    # A fresh id per call by default — mirrors a real provider, which
    # always generates a unique tool_call id. A hardcoded default shared
    # across multiple scripted steps in the same test would silently
    # collide in `AgentService`'s id-to-name mapping (tool_call ids are
    # assumed unique for the whole run), masking a real multi-tool-call
    # scenario as if only one tool had ever been called.
    resolved_call_id = call_id or f"call_{uuid.uuid4().hex[:8]}"
    return CompletionResponse(
        content="",
        model="test-model",
        provider="test",
        finish_reason="tool_calls",
        usage=TokenUsage(),
        tool_calls=[ToolCall(id=resolved_call_id, name=tool_name, arguments=json.dumps(arguments))],
    )


def make_multi_tool_call_completion(
    *, calls: list[tuple[str, dict[str, Any]]]
) -> CompletionResponse:
    return CompletionResponse(
        content="",
        model="test-model",
        provider="test",
        finish_reason="tool_calls",
        usage=TokenUsage(),
        tool_calls=[
            ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=json.dumps(args))
            for name, args in calls
        ],
    )


def make_final_completion(content: str) -> CompletionResponse:
    return CompletionResponse(
        content=content,
        model="test-model",
        provider="test",
        finish_reason="stop",
        usage=TokenUsage(),
    )
