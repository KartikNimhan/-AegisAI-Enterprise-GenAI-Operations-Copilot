"""Shared fixtures for evaluation tests.

`db_session` opens a session on the test database and rolls everything back at
the end. Before that it runs the same check as the integration suite
(`tests/live_database.py`): `active_targets()` must show the isolation guard
ran, the URL must already have passed its rules, and the server must report the
configured `_test` database at the code's migration, or the whole run stops. A
missing or unreachable database goes through the same `service_unavailable`
rule: a skip locally, a failure when the run requires its services
(`AEGIS_REQUIRE_SERVICES=1`), so a broken database can never leave the
evaluation tests silently skipped.

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

from app.db.session import AsyncSessionLocal
from tests.live_database import require_test_database

from ..unit.multi_agent.conftest import async_client as async_client
from ..unit.multi_agent.conftest import fake_documents as fake_documents
from ..unit.multi_agent.conftest import orchestrator_env as orchestrator_env

__all__ = ["db_session", "async_client", "orchestrator_env", "fake_documents"]


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    await require_test_database()
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
