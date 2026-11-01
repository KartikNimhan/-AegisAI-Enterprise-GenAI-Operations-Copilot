"""Shared fixtures for integration tests that need a real database session.

`db_session` opens one transaction per test and rolls it back at the end
(classic "transactional test" isolation) — repositories only ever `flush()`,
never `commit()`, so nothing a test does is ever actually durable, and no
per-test cleanup code is needed.

Documents and conversations must have an owner, so it also provisions a real
organization and member user for the test (see `scoping.py`), and — unless the test
asks for `real_auth` — makes the HTTP app's test principal that same user, so a request
made through the app is owned by a row that exists. The few tests whose code under test
commits (document uploads) would leave that user behind, so teardown removes everything
the test's user owns, then the user and organization.

Test isolation (see `backend/tests/isolation.py`): the database used here is only ever the test
database named by `TEST_DATABASE_URL`, already checked to end in `_test`. Before the first test
uses it, `tests/live_database.py` also asks the server which database it really is and which
migration it is at, and stops the whole run if either is wrong. The evaluation suite's
`db_session` uses the same module.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_principal
from app.db.session import AsyncSessionLocal
from app.domain.models.agent_memory import AgentMemory
from app.domain.models.conversation import Conversation
from app.domain.models.document import Document
from app.domain.models.organization import Organization
from app.domain.models.user import User
from app.main import app
from tests.live_database import require_test_database, verify_test_database_once

from .scoping import TestUser, create_user


@pytest.fixture(autouse=True)
async def _isolated_test_database() -> None:
    """Runs the live check before any integration test, including ones that connect through the
    application without `db_session`."""
    await verify_test_database_once()


async def _remove_organizations(session: AsyncSession, organizations: set[uuid.UUID]) -> None:
    """Deletes these organizations with everything they own: agent memories, documents (their
    chunks and embeddings cascade in the database), conversations (and messages), then users,
    then the organizations.
    Only ever called with organizations a test itself created."""
    await session.execute(delete(AgentMemory).where(AgentMemory.organization_id.in_(organizations)))
    await session.execute(delete(Document).where(Document.organization_id.in_(organizations)))
    await session.execute(
        delete(Conversation).where(Conversation.organization_id.in_(organizations))
    )
    await session.execute(delete(User).where(User.organization_id.in_(organizations)))
    await session.execute(delete(Organization).where(Organization.id.in_(organizations)))
    await session.commit()


async def _remove_everything_owned_by(session: AsyncSession, owner: TestUser) -> None:
    """Best-effort cleanup for tests that committed: removes every organization the test created
    (its own, and any made with `create_user`) with what they own."""
    organizations = {owner.organization_id} | session.info.get("test_organizations", set())
    await _remove_organizations(session, organizations)


@pytest.fixture
async def db_session(request: pytest.FixtureRequest) -> AsyncIterator[AsyncSession]:
    await require_test_database()
    async with AsyncSessionLocal() as session:
        owner = await create_user(session)
        session.info["test_user"] = owner
        previous = app.dependency_overrides.get(get_current_principal)
        if "real_auth" not in request.fixturenames:
            app.dependency_overrides[get_current_principal] = lambda: owner.principal
        try:
            yield session
        finally:
            await session.rollback()
            if previous is None:
                app.dependency_overrides.pop(get_current_principal, None)
            else:
                app.dependency_overrides[get_current_principal] = previous
            await _remove_everything_owned_by(session, owner)


@pytest.fixture
async def committed_user(db_session: AsyncSession) -> AsyncIterator[TestUser]:
    """A user and organization COMMITTED through their own session.

    For tests whose request uses the application's real `get_session` dependency: that opens a
    different connection, which cannot see the rows `db_session` has only flushed, so the
    ownership foreign key would reject a conversation owned by `db_session`'s user. The app's
    test principal is pointed at this committed user; `db_session`'s own teardown restores the
    original override. Depending on `db_session` also applies its skip-if-Postgres-is-unreachable
    check and makes sure its principal override is installed first (this one then replaces it).

    Cleanup removes only the organization created here, with whatever it owns.
    """
    async with AsyncSessionLocal() as setup:
        user = await create_user(setup)
        organizations = set(setup.info["test_organizations"])
        await setup.commit()
    app.dependency_overrides[get_current_principal] = lambda: user.principal
    try:
        yield user
    finally:
        async with AsyncSessionLocal() as cleanup:
            await _remove_organizations(cleanup, organizations)
