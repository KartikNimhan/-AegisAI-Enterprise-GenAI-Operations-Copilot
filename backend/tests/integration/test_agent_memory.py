"""Agent memory against a real PostgreSQL database.

NOTE: written without a database available in the authoring environment, so these tests have not
been executed yet; they skip when Postgres is unreachable (see conftest.db_session). The offline
twin, which runs the same service and repository over SQLite, is tests/unit/memory/.

What only PostgreSQL can show: the composite foreign key that ties an owner to the row's
organization, the unique (owner, content hash) constraint, the content-length CHECK, savepoint
containment of a constraint violation, and the ownership predicate on the real column types.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.repositories.agent_memory_repository import AgentMemoryRepository
from app.domain.enums.memory_kind import MemoryKind, MemorySource
from app.domain.enums.user_role import UserRole
from app.memory.service import AgentMemoryService, build_memory_service

from .scoping import TestUser, create_user, owner_of

pytestmark = pytest.mark.integration

SETTINGS = Settings(agent_memory_max_items_per_user=3)
NOW = datetime.now(UTC)


def service_for(session: AsyncSession, user: TestUser) -> AgentMemoryService:
    return build_memory_service(session, user.scope, SETTINGS)


async def test_a_memory_is_private_to_its_owner(db_session: AsyncSession) -> None:
    alice = owner_of(db_session)
    colleague = await create_user(db_session, organization_id=alice.organization_id)
    admin = await create_user(
        db_session, organization_id=alice.organization_id, role=UserRole.ADMIN
    )
    outsider = await create_user(db_session)
    memory, _ = await service_for(db_session, alice).remember("Alice's private preference")

    for other in (colleague, admin, outsider):
        service = service_for(db_session, other)
        assert await service.list_all() == []
        assert await service.recall("private preference") == []
        assert await service.update(memory.id, "tampered") is None
        assert await service.delete(memory.id) is False
        assert await service.clear() == 0
    assert [m.id for m in await service_for(db_session, alice).list_all()] == [memory.id]


async def test_the_database_rejects_an_owner_outside_the_rows_organization(
    db_session: AsyncSession,
) -> None:
    alice = owner_of(db_session)
    other_org = await create_user(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO agent_memories (id, owner_user_id, organization_id, kind, "
                    "source, content, content_hash, expires_at) "
                    "VALUES (:id, :u, :o, 'fact', 'agent', 'x', 'h', now())"
                ),
                {"id": uuid.uuid4(), "u": alice.user_id, "o": other_org.organization_id},
            )


async def test_the_database_enforces_content_length_and_the_enums(db_session: AsyncSession) -> None:
    alice = owner_of(db_session)
    base = (
        "INSERT INTO agent_memories (id, owner_user_id, organization_id, kind, source, "
        "content, content_hash, expires_at) VALUES (:id, :u, :o, {kind}, 'agent', {content}, "
        "'h', now())"
    )
    for kind, content in (("'fact'", "''"), ("'fact'", "repeat('x', 2001)"), ("'secret'", "'x'")):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(base.format(kind=kind, content=content)),
                    {"id": uuid.uuid4(), "u": alice.user_id, "o": alice.organization_id},
                )


async def test_the_same_note_is_unique_per_owner_but_not_across_owners(
    db_session: AsyncSession,
) -> None:
    alice = owner_of(db_session)
    bob = await create_user(db_session)

    first, created = await service_for(db_session, alice).remember("Prefers dark mode")
    again, created_again = await service_for(db_session, alice).remember("prefers DARK mode")
    bobs, bob_created = await service_for(db_session, bob).remember("Prefers dark mode")

    assert created and not created_again and again.id == first.id
    assert bob_created and bobs.id != first.id


async def test_a_constraint_violation_is_contained_by_the_savepoint(
    db_session: AsyncSession,
) -> None:
    alice = owner_of(db_session)
    repo = AgentMemoryRepository(db_session, alice.scope)
    await repo.create(
        content="dup",
        content_hash="same-hash",
        kind=MemoryKind.FACT,
        source=MemorySource.AGENT,
        now=NOW,
        expires_at=NOW + timedelta(days=1),
    )

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repo.create(
                content="dup again",
                content_hash="same-hash",
                kind=MemoryKind.FACT,
                source=MemorySource.AGENT,
                now=NOW,
                expires_at=NOW + timedelta(days=1),
            )

    # The surrounding transaction is still usable.
    assert len(await service_for(db_session, alice).list_all()) == 1


async def test_limits_and_expiry_hold_on_the_real_database(db_session: AsyncSession) -> None:
    alice = owner_of(db_session)
    service = service_for(db_session, alice)
    for n in range(3):
        await service.remember(f"note {n}")
    with pytest.raises(Exception, match="memory is full"):
        await service.remember("note 4")

    await db_session.execute(
        text(
            "UPDATE agent_memories SET expires_at = now() - interval '1 day' WHERE owner_user_id=:u"
        ),
        {"u": alice.user_id},
    )
    assert await service.list_all() == []
    _, created = await service.remember("fresh")
    assert created is True
    assert [m.content for m in await service.list_all()] == ["fresh"]


async def test_a_user_who_owns_memories_cannot_be_deleted_out_from_under_them(
    db_session: AsyncSession,
) -> None:
    alice = owner_of(db_session)
    await service_for(db_session, alice).remember("keeps the user in place")

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": alice.user_id})
