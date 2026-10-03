"""Shared fixtures for evaluation tests that need a real database session.

Identical to tests/integration/conftest.py's `db_session` — duplicated
rather than imported across directories, since pytest fixture discovery is
directory-scoped and this is the only fixture evaluation tests need from
there.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, check_database


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not await check_database(timeout=2.0):
        pytest.skip("Postgres is not reachable — start it via `docker compose up -d postgres`")
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
