"""Unit tests for ConversationService (pass-through over the repository)."""

from __future__ import annotations

import uuid

from app.services.conversation_service import ConversationService

from .doubles import FakeConversationRepository


async def test_list_conversations_returns_most_recently_updated_first() -> None:
    repo = FakeConversationRepository()
    service = ConversationService(repo)  # type: ignore[arg-type]
    first = await repo.create(title="first")
    second = await repo.create(title="second")
    await repo.touch(first)  # bump first to be most recently updated

    result = await service.list_conversations()

    assert [c.id for c in result] == [first.id, second.id]


async def test_get_conversation_returns_none_when_missing() -> None:
    service = ConversationService(FakeConversationRepository())  # type: ignore[arg-type]

    assert await service.get_conversation(uuid.uuid4()) is None


async def test_delete_conversation_returns_false_when_missing() -> None:
    service = ConversationService(FakeConversationRepository())  # type: ignore[arg-type]

    assert await service.delete_conversation(uuid.uuid4()) is False


async def test_delete_conversation_returns_true_when_deleted() -> None:
    repo = FakeConversationRepository()
    service = ConversationService(repo)  # type: ignore[arg-type]
    conversation = await repo.create(title="x")

    assert await service.delete_conversation(conversation.id) is True
    assert conversation.id not in repo.conversations
