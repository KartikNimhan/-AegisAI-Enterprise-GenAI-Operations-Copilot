"""Integration tests for ConversationRepository against real PostgreSQL.

Requires migrations to have been applied (`alembic upgrade head`) — see
docs/development/setup.md. Skips automatically if Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.message_repository import MessageRepository
from app.domain.enums.message_role import MessageRole

pytestmark = pytest.mark.integration


async def test_create_and_get_conversation(db_session: AsyncSession) -> None:
    repo = ConversationRepository(db_session)

    created = await repo.create(title="My conversation")
    fetched = await repo.get(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "My conversation"
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_get_returns_none_for_unknown_id(db_session: AsyncSession) -> None:
    repo = ConversationRepository(db_session)

    assert await repo.get(uuid.uuid4()) is None


async def test_get_with_messages_returns_ordered_messages(db_session: AsyncSession) -> None:
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    conversation = await conversations.create(title="x")

    await messages.add(conversation_id=conversation.id, role=MessageRole.USER, content="first")
    await messages.add(
        conversation_id=conversation.id, role=MessageRole.ASSISTANT, content="second"
    )
    await messages.add(conversation_id=conversation.id, role=MessageRole.USER, content="third")

    fetched = await conversations.get_with_messages(conversation.id)

    assert fetched is not None
    assert [m.content for m in fetched.messages] == ["first", "second", "third"]


async def test_list_orders_by_most_recently_updated(db_session: AsyncSession) -> None:
    repo = ConversationRepository(db_session)
    first = await repo.create(title="first")
    second = await repo.create(title="second")
    # Windows' clock resolution can be as coarse as ~15ms, so two
    # back-to-back timestamps can otherwise land in the exact same tick —
    # this touch would then tie with (not clearly follow) `second`'s
    # creation timestamp, making the assertion below flaky rather than
    # actually wrong. A real "most recently updated" list only needs to
    # get this right at ordinary human-interaction timescales.
    await asyncio.sleep(0.02)
    await repo.touch(first)
    await db_session.flush()

    result = await repo.list(limit=10)

    ids = [c.id for c in result]
    assert ids.index(first.id) < ids.index(second.id)


async def test_delete_removes_conversation_and_cascades_messages(
    db_session: AsyncSession,
) -> None:
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    conversation = await conversations.create(title="to delete")
    await messages.add(conversation_id=conversation.id, role=MessageRole.USER, content="hi")

    deleted = await conversations.delete(conversation.id)

    assert deleted is True
    assert await conversations.get(conversation.id) is None
    assert await messages.list_by_conversation(conversation.id) == []


async def test_delete_returns_false_for_unknown_id(db_session: AsyncSession) -> None:
    repo = ConversationRepository(db_session)

    assert await repo.delete(uuid.uuid4()) is False
