"""Unit tests never connect to PostgreSQL.

Every unit test runs with asyncpg's connect functions replaced by one that raises
`UnitTestDatabaseAccessError`. SQLAlchemy's asyncpg dialect and asyncpg's pool both connect through
these functions, so neither the application's engine nor a test's own engine can reach a server.
In-memory SQLite (used by some unit tests to execute SQL) is unaffected.

A test that needs a real database belongs in `backend/tests/integration/`, where it runs only
against the isolated test database (see `backend/tests/isolation.py`).
"""

from __future__ import annotations

from collections.abc import Iterator
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
