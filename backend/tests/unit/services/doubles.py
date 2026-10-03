"""Test doubles for ChatService/ConversationService unit tests.

Not a test module itself (no `test_*` functions), so pytest won't collect
it. None of these touch a real database or the real Groq SDK.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.domain.models.conversation import Conversation
from app.domain.models.message import Message
from app.llm.gateway import LLMGateway
from app.llm.schemas import ChatMessage, CompletionResponse, ModelRole, StreamChunk


class FakeSession:
    """Stand-in for AsyncSession — only what ChatService touches directly."""

    def __init__(self) -> None:
        self.rollback_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1


class FakeConversationRepository:
    def __init__(self) -> None:
        self.conversations: dict[uuid.UUID, Conversation] = {}
        self.touch_calls: list[uuid.UUID] = []

    async def create(self, *, title: str | None = None) -> Conversation:
        now = datetime.now(UTC)
        conversation = Conversation(id=uuid.uuid4(), title=title, created_at=now, updated_at=now)
        self.conversations[conversation.id] = conversation
        return conversation

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def get_with_messages(self, conversation_id: uuid.UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list(self, *, limit: int = 50) -> list[Conversation]:
        return sorted(self.conversations.values(), key=lambda c: c.updated_at, reverse=True)[:limit]

    async def delete(self, conversation_id: uuid.UUID) -> bool:
        return self.conversations.pop(conversation_id, None) is not None

    async def touch(self, conversation: Conversation) -> None:
        self.touch_calls.append(conversation.id)
        conversation.updated_at = datetime.now(UTC)


class FakeMessageRepository:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def add(
        self,
        *,
        conversation_id: uuid.UUID,
        role: Any,
        content: str,
        **kwargs: Any,
    ) -> Message:
        message = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=datetime.now(UTC),
            **kwargs,
        )
        self.messages.append(message)
        return message

    async def list_by_conversation(self, conversation_id: uuid.UUID) -> list[Message]:
        return [m for m in self.messages if m.conversation_id == conversation_id]


class ScriptedChatGateway(LLMGateway):
    """Subclasses LLMGateway purely for type compatibility where one is
    expected; `__init__` deliberately skips the real settings/provider
    setup and overrides every method ChatService calls."""

    def __init__(
        self,
        *,
        completion: CompletionResponse | None = None,
        completion_error: Exception | None = None,
        stream_chunks: list[StreamChunk] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self._completion = completion
        self._completion_error = completion_error
        self._stream_chunks = stream_chunks or []
        self._stream_error = stream_error
        self.chat_completion_calls: list[list[ChatMessage]] = []
        self.stream_calls: list[list[ChatMessage]] = []

    async def chat_completion(
        self, *, model_role: ModelRole, messages: list[ChatMessage], **kwargs: Any
    ) -> CompletionResponse:
        self.chat_completion_calls.append(messages)
        if self._completion_error is not None:
            raise self._completion_error
        assert self._completion is not None
        return self._completion

    async def stream_chat_completion(
        self, *, model_role: ModelRole, messages: list[ChatMessage], **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        self.stream_calls.append(messages)
        for chunk in self._stream_chunks:
            yield chunk
        if self._stream_error is not None:
            raise self._stream_error

    def model_metadata(self) -> dict[str, str]:
        return {"provider": "fake", "primary": "fake-model"}
