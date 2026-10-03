"""Integration test: /health/ready against real dependencies, end to end.

Uses httpx.AsyncClient (not the sync TestClient fixture) so the request runs
on the same event loop as this test. The sync TestClient drives the ASGI app
from a separate internal loop/thread, which would reuse the module-level
async engine's pooled connections across event loops and fail.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.redis import check_redis
from app.db.session import check_database
from app.main import app

pytestmark = pytest.mark.integration


async def test_readiness_is_ok_with_live_dependencies() -> None:
    if not await check_database(timeout=2.0) or not await check_redis(timeout=2.0):
        pytest.skip("Postgres/Redis not reachable — start them via `docker compose up -d`")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        response = await async_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "redis": "ok"}
