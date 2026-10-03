"""Integration tests for MessageRepository against real PostgreSQL.

Requires migrations to have been applied (`alembic upgrade head`). Skips
automatically if Postgres is unreachable.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.message_repository import MessageRepository
from app.domain.enums.message_role import MessageRole

pytestmark = pytest.mark.integration


async def test_add_persists_all_fields(db_session: AsyncSession) -> None:
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    conversation = await conversations.create(title="x")

    message = await messages.add(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content="hello",
        model="openai/gpt-oss-120b",
        provider="groq",
        finish_reason="stop",
        request_id="req_1",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
    )

    assert message.id is not None
    assert message.created_at is not None
    assert message.role == MessageRole.ASSISTANT
    assert message.model == "openai/gpt-oss-120b"
    assert message.total_tokens == 15


async def test_add_without_optional_fields_defaults_to_none(db_session: AsyncSession) -> None:
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    conversation = await conversations.create(title="x")

    message = await messages.add(
        conversation_id=conversation.id, role=MessageRole.USER, content="hi"
    )

    assert message.model is None
    assert message.input_tokens is None
    assert message.total_tokens is None


async def test_list_by_conversation_orders_by_created_at(db_session: AsyncSession) -> None:
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    conversation = await conversations.create(title="x")

    for content in ("one", "two", "three"):
        await messages.add(conversation_id=conversation.id, role=MessageRole.USER, content=content)

    result = await messages.list_by_conversation(conversation.id)

    assert [m.content for m in result] == ["one", "two", "three"]


async def test_list_by_conversation_only_returns_matching_conversation(
    db_session: AsyncSession,
) -> None:
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    conversation_a = await conversations.create(title="a")
    conversation_b = await conversations.create(title="b")
    await messages.add(conversation_id=conversation_a.id, role=MessageRole.USER, content="in a")
    await messages.add(conversation_id=conversation_b.id, role=MessageRole.USER, content="in b")

    result = await messages.list_by_conversation(conversation_a.id)

    assert [m.content for m in result] == ["in a"]
