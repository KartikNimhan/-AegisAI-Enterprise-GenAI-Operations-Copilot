"""The server-side check every database-backed test fixture runs before touching the database.

Shared by `tests/integration/conftest.py` and `tests/evaluation/conftest.py`, so both suites use
exactly the same rules. On top of the URL rules in `isolation.py` (applied before anything
connects), the first use asks the server which database it really is and which migration it is
at, and stops the whole run if either is wrong. The result is cached for the rest of the run.

`active_targets()` raises if the isolation guard has not run in this process, so a fixture built
on this module fails closed instead of connecting wherever `.env` points.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.session import AsyncSessionLocal, check_database
from tests.integration.requirements import service_unavailable
from tests.isolation import (
    active_targets,
    alembic_head,
    migration_message,
    wrong_database_message,
)

UNCONFIGURED = "unconfigured"
UNREACHABLE = "unreachable"
VERIFIED = "verified"
_state: str | None = None


async def verify_test_database_once() -> str:
    """`unconfigured`, `unreachable` or `verified`; checked once per run. Stops the run when the
    server is not the configured `_test` database or is not at the code's migration."""
    global _state
    targets = active_targets()
    if not targets.database_configured:
        return UNCONFIGURED
    if _state is not None:
        return _state
    if not await check_database(timeout=2.0):
        _state = UNREACHABLE
        return _state

    async with AsyncSessionLocal() as session:
        current = await session.scalar(text("SELECT current_database()"))
        has_versions = await session.scalar(
            text("SELECT to_regclass('alembic_version') IS NOT NULL")
        )
        revision = (
            await session.scalar(text("SELECT version_num FROM alembic_version"))
            if has_versions
            else None
        )
    problem = wrong_database_message(expected=targets.database_name, actual=current)
    if problem is None:
        problem = migration_message(database=current, revision=revision, head=alembic_head())
    if problem is not None:
        pytest.exit(problem, returncode=3)
    _state = VERIFIED
    return _state


async def require_test_database() -> None:
    """For a fixture that needs the database: skips (or fails, under `AEGIS_REQUIRE_SERVICES=1`)
    when no test database is configured or reachable, after the live check."""
    state = await verify_test_database_once()
    if state == UNCONFIGURED:
        service_unavailable(
            "No test database is configured: copy .env.test.example to .env.test and set "
            "TEST_DATABASE_URL (see docs/development/setup.md, 'Running tests safely')"
        )
    if state == UNREACHABLE:
        service_unavailable(
            f"The test database {active_targets().database_name!r} is not reachable — start "
            "PostgreSQL, then check it with `uv run python scripts/test_db.py check`"
        )


def reset_for_tests() -> None:
    """Forgets the cached result (unit tests of this module only)."""
    global _state
    _state = None
