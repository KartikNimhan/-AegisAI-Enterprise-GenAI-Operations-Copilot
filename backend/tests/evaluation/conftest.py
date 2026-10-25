"""Shared fixtures for evaluation tests.

`db_session` is identical to tests/integration/conftest.py's fixture of
the same name — duplicated rather than imported across directories,
since pytest fixture discovery is directory-scoped. An unreachable Postgres
goes through the same `service_unavailable` rule: a skip locally, a failure
when the run requires its services (`AEGIS_REQUIRE_SERVICES=1`), so a broken
database can never leave the evaluation tests silently skipped.

`async_client`/`orchestrator_env`/`fake_documents` are re-exported
(imported, not duplicated) from tests/unit/multi_agent/conftest.py for
the same directory-scoping reason — test_multi_agent_evaluation.py needs
the exact same deterministic multi-agent test harness
tests/unit/multi_agent/test_orchestrator.py already uses, not a second
implementation of it.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, check_database

from ..integration.requirements import service_unavailable
from ..unit.multi_agent.conftest import async_client as async_client
from ..unit.multi_agent.conftest import fake_documents as fake_documents
from ..unit.multi_agent.conftest import orchestrator_env as orchestrator_env

__all__ = ["db_session", "async_client", "orchestrator_env", "fake_documents"]


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not await check_database(timeout=2.0):
        service_unavailable(
            "Postgres is not reachable — start it via `docker compose up -d postgres`"
        )
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
