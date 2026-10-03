"""Shared fixtures for integration tests that need a real database session.

`db_session` opens one transaction per test and rolls it back at the end
(classic "transactional test" isolation) — repositories only ever `flush()`,
never `commit()`, so nothing a test does is ever actually durable, and no
per-test cleanup code is needed.
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
