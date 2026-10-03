"""Integration test: requires a live PostgreSQL instance.

Run via `docker compose up -d postgres` locally, or rely on the CI workflow's
Postgres service container. Skips itself (rather than failing) when the
database is unreachable, so `pytest` stays green without Docker running.
"""

import pytest

from app.db.session import check_database

pytestmark = pytest.mark.integration


async def test_can_connect_to_postgres() -> None:
    if not await check_database(timeout=2.0):
        pytest.skip("Postgres is not reachable — start it via `docker compose up -d postgres`")
