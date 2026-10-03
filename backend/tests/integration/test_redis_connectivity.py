"""Integration test: requires a live Redis instance.

Run via `docker compose up -d redis` locally, or rely on the CI workflow's
Redis service container. Skips itself (rather than failing) when Redis is
unreachable, so `pytest` stays green without Docker running.
"""

import pytest

from app.db.redis import check_redis

pytestmark = pytest.mark.integration


async def test_can_connect_to_redis() -> None:
    if not await check_redis(timeout=2.0):
        pytest.skip("Redis is not reachable — start it via `docker compose up -d redis`")
