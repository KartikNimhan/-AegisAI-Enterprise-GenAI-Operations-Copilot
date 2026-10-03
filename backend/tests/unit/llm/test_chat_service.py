"""Unit tests for ChatService: the thin wrapper routes call into the gateway through."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.llm.gateway import LLMGateway
from app.llm.schemas import (
    ChatMessage,
    ChatRole,
    CompletionResponse,
    ModelRole,
    StreamChunk,
    TokenUsage,
)
from app.services.chat_service import ChatService


class FakeGateway(LLMGateway):
    """Subclasses LLMGateway purely so it type-checks where one is expected;
    `__init__` deliberately skips the real settings/provider setup."""

    def __init__(self) -> None:
        self.chat_completion_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def chat_completion(
        self, *, model_role: ModelRole, messages: list[ChatMessage], **_: Any
    ) -> CompletionResponse:
        self.chat_completion_calls.append({"model_role": model_role, "messages": messages})
        return CompletionResponse(
            content="hi", model="m", provider="fake", usage=TokenUsage(), request_id="r1"
        )

    async def stream_chat_completion(
        self, *, model_role: ModelRole, messages: list[ChatMessage], **_: Any
    ) -> AsyncIterator[StreamChunk]:
        self.stream_calls.append({"model_role": model_role, "messages": messages})
        yield StreamChunk(delta="hi", is_final=True)


async def test_complete_sends_a_single_user_message() -> None:
    gateway = FakeGateway()
    service = ChatService(gateway)

    result = await service.complete(message="hello", model_role=ModelRole.PRIMARY)

    assert result.content == "hi"
    call = gateway.chat_completion_calls[0]
    assert call["model_role"] == ModelRole.PRIMARY
    assert call["messages"] == [ChatMessage(role=ChatRole.USER, content="hello")]


async def test_stream_sends_a_single_user_message() -> None:
    gateway = FakeGateway()
    service = ChatService(gateway)

    chunks = [chunk async for chunk in service.stream(message="hello", model_role=ModelRole.FAST)]

    assert chunks[0].delta == "hi"
    assert gateway.stream_calls[0]["model_role"] == ModelRole.FAST
