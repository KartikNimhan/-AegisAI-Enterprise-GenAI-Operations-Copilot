"""A conversation's messages come back in a total, chronological order.

Regression: messages were sorted by `created_at` alone, whose default is PostgreSQL's `now()`: the
start of the TRANSACTION. A turn stores the user's message and the reply in one transaction, so
both had the same timestamp, and which came first (in the model's history and in the conversation
view) was up to the database. Real SQL runs here on SQLite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, configure_mappers
from sqlalchemy.pool import StaticPool

from app.auth.scope import AccessScope
from app.db.repositories.message_repository import MessageRepository
from app.domain.enums.message_role import MessageRole
from app.domain.models.conversation import Conversation
from app.domain.models.message import Message

USER = uuid.uuid4()
ORG = uuid.uuid4()
SCOPE = AccessScope.for_user(user_id=USER, organization_id=ORG)
SAME_INSTANT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


class AsyncAdapter:
    """Just enough of AsyncSession for MessageRepository, over a sync SQLite session."""

    def __init__(self, session: Session) -> None:
        self.sync = session

    async def execute(self, statement: Any) -> Any:
        return self.sync.execute(statement)

    async def scalar(self, statement: Any) -> Any:
        return self.sync.scalar(statement)

    def add(self, obj: Any) -> None:
        self.sync.add(obj)

    async def flush(self) -> None:
        self.sync.flush()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Conversation.__table__.create(engine)  # type: ignore[attr-defined]
    Message.__table__.create(engine)  # type: ignore[attr-defined]
    session = Session(engine)
    conversation = Conversation(id=uuid.uuid4(), owner_user_id=USER, organization_id=ORG, title="t")
    session.add(conversation)
    session.flush()
    yield session, conversation
    session.close()
    engine.dispose()


def store(session: Session, conversation: Conversation, role: MessageRole, content: str) -> None:
    session.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role=role,
            content=content,
            created_at=SAME_INSTANT,
        )
    )
    session.flush()


async def test_a_turn_stored_with_one_timestamp_still_lists_question_before_answer(db) -> None:
    session, conversation = db
    # Worst case: the reply happens to be stored (or returned by the database) first.
    store(session, conversation, MessageRole.ASSISTANT, "the answer")
    store(session, conversation, MessageRole.USER, "the question")
    repository = MessageRepository(AsyncAdapter(session), SCOPE)  # type: ignore[arg-type]

    listed = await repository.list_by_conversation(conversation.id)

    assert [m.content for m in listed] == ["the question", "the answer"]


async def test_recent_history_is_the_newest_messages_oldest_first(db) -> None:
    session, conversation = db
    repository = MessageRepository(AsyncAdapter(session), SCOPE)  # type: ignore[arg-type]
    for index in range(6):
        role = MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT
        await repository.add(conversation_id=conversation.id, role=role, content=f"m{index}")

    recent = await repository.list_recent(conversation.id, limit=4)

    assert [m.content for m in recent] == ["m2", "m3", "m4", "m5"]
    assert [m.content for m in await repository.list_recent(conversation.id, limit=100)] == [
        f"m{index}" for index in range(6)
    ]


async def test_recent_history_breaks_timestamp_ties_the_same_way(db) -> None:
    session, conversation = db
    store(session, conversation, MessageRole.ASSISTANT, "the answer")
    store(session, conversation, MessageRole.USER, "the question")
    repository = MessageRepository(AsyncAdapter(session), SCOPE)  # type: ignore[arg-type]

    assert [m.content for m in await repository.list_recent(conversation.id, limit=2)] == [
        "the question",
        "the answer",
    ]
    assert [m.content for m in await repository.list_recent(conversation.id, limit=1)] == [
        "the answer"
    ]


async def test_new_messages_get_strictly_increasing_timestamps_even_on_a_frozen_clock(db) -> None:
    session, conversation = db
    repository = MessageRepository(
        AsyncAdapter(session),  # type: ignore[arg-type]
        SCOPE,
        clock=lambda: SAME_INSTANT,
    )

    stored = [
        await repository.add(conversation_id=conversation.id, role=role, content=role.value)
        for role in (MessageRole.USER, MessageRole.ASSISTANT, MessageRole.USER)
    ]

    stamps = [m.created_at for m in stored]
    assert stamps == sorted(stamps) and len(set(stamps)) == 3


async def test_another_users_conversation_has_no_recent_history(db) -> None:
    session, conversation = db
    store(session, conversation, MessageRole.USER, "private")
    stranger = AccessScope.for_user(user_id=uuid.uuid4(), organization_id=ORG)

    repository = MessageRepository(AsyncAdapter(session), stranger)  # type: ignore[arg-type]

    assert await repository.list_recent(conversation.id, limit=10) == []


def test_the_conversation_view_uses_the_same_total_order() -> None:
    configure_mappers()
    order = [
        str(column.compile(dialect=postgresql.dialect()))
        for column in Conversation.messages.property.order_by  # type: ignore[union-attr]
    ]

    assert order[0] == "messages.created_at"
    assert order[1].startswith("CASE WHEN (messages.role")
    assert order[2] == "messages.id"
