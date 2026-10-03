"""Tests for the /health and /health/ready endpoints.

These are true unit tests: database/redis connectivity checks are
monkeypatched so the result is deterministic regardless of whether a real
Postgres/Redis is running. See backend/tests/integration for live checks.
"""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_200_when_dependencies_are_up(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.health.check_database", _async_true)
    monkeypatch.setattr("app.api.v1.health.check_redis", _async_true)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "redis": "ok"}


def test_readiness_returns_503_when_database_is_down(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.health.check_database", _async_false)
    monkeypatch.setattr("app.api.v1.health.check_redis", _async_true)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable", "redis": "ok"}


def test_readiness_returns_503_when_redis_is_down(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.health.check_database", _async_true)
    monkeypatch.setattr("app.api.v1.health.check_redis", _async_false)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "ok", "redis": "unavailable"}


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False
