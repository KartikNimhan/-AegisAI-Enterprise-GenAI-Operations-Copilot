"""Unit tests never connect to PostgreSQL.

Every unit test runs with asyncpg's connect functions replaced by one that raises
`UnitTestDatabaseAccessError`. SQLAlchemy's asyncpg dialect and asyncpg's pool both connect through
these functions, so neither the application's engine nor a test's own engine can reach a server.
In-memory SQLite (used by some unit tests to execute SQL) is unaffected.

Blocking new connections is not enough on its own. When the whole suite runs in one process (as in
CI, where `backend/tests/integration/` is collected before `backend/tests/unit/`), an integration
test can leave a live connection in the application engine's pool, and `engine.connect()` would hand
it to a unit test without ever calling `asyncpg.connect`. So before each unit test the engine's pool
is disposed: SQLAlchemy closes every checked-in connection and replaces the pool. A connection still
checked out elsewhere is NOT closed by this, but it no longer belongs to the engine's pool, so the
engine can never give it to a unit test.

A test that needs a real database belongs in `backend/tests/integration/`, where it runs only
against the isolated test database (see `backend/tests/isolation.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import asyncpg
import asyncpg.connection
import pytest


class UnitTestDatabaseAccessError(RuntimeError):
    """A unit test tried to open a PostgreSQL connection."""


MESSAGE = (
    "Unit tests must not connect to PostgreSQL. Fake the database layer, or move the test to "
    "backend/tests/integration/, where it runs only against the isolated test database."
)


async def refuse_connection(*_args: Any, **_kwargs: Any) -> Any:
    raise UnitTestDatabaseAccessError(MESSAGE)


@pytest.fixture(autouse=True)
def _no_postgres_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(asyncpg, "connect", refuse_connection)
    monkeypatch.setattr(asyncpg.connection, "connect", refuse_connection)
    yield


@pytest.fixture(autouse=True)
async def _no_pooled_postgres_connections() -> AsyncIterator[None]:
    """Empties the application engine's pool before each unit test (see the module docstring).

    Async on purpose: `AsyncEngine.dispose()` closes the pooled asyncpg connections on the event
    loop that opened them, which is the session-scoped loop every test and fixture shares
    (`asyncio_default_fixture_loop_scope = "session"` in pyproject.toml). With the pool empty and
    `asyncpg.connect` blocked, no unit test can obtain a connection. Costs nothing when the pool is
    already empty, which is the usual case."""
    # Imported here, not at module level: the application must be imported only after the test
    # environment has been configured (tests/__init__.py).
    from app.db.session import engine

    await engine.dispose()
    yield
