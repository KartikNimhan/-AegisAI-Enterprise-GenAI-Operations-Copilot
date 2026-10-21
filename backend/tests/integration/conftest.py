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
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_principal
from app.db.session import AsyncSessionLocal, check_database
from app.domain.models.conversation import Conversation
from app.domain.models.document import Document
from app.domain.models.organization import Organization
from app.domain.models.user import User
from app.main import app

from .scoping import TestUser, create_user


async def _remove_everything_owned_by(session: AsyncSession, owner: TestUser) -> None:
    """Best-effort cleanup for tests that committed: removes every organization the test created
    (its own, and any made with `create_user`) with what they own."""
    organizations = {owner.organization_id} | session.info.get("test_organizations", set())
    await session.execute(delete(Document).where(Document.organization_id.in_(organizations)))
    await session.execute(
        delete(Conversation).where(Conversation.organization_id.in_(organizations))
    )
    await session.execute(delete(User).where(User.organization_id.in_(organizations)))
    await session.execute(delete(Organization).where(Organization.id.in_(organizations)))
    await session.commit()


@pytest.fixture
async def db_session(request: pytest.FixtureRequest) -> AsyncIterator[AsyncSession]:
    if not await check_database(timeout=2.0):
        pytest.skip("Postgres is not reachable — start it via `docker compose up -d postgres`")
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
