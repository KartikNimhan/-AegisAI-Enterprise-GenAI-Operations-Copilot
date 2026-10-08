"""Unit tests for GET /api/v1/system/status.

Database/redis connectivity checks are monkeypatched (same pattern as
tests/unit/test_health.py) — deterministic regardless of whether a real
Postgres/Redis is running.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False


def test_status_reports_ok_when_dependencies_are_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.v1.system.check_database", _async_true)
    monkeypatch.setattr("app.api.v1.system.check_redis", _async_true)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"] == "ok"
    assert payload["redis"] == "ok"
    assert payload["mcp_server"] == "aegisai-internal"
    assert payload["trusted_a2a_agents"] == ["http://localhost:8000"]


def test_status_reports_unavailable_when_database_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.v1.system.check_database", _async_false)
    monkeypatch.setattr("app.api.v1.system.check_redis", _async_true)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    assert response.json()["database"] == "unavailable"


def test_status_never_claims_llm_configured_without_a_key(client: TestClient) -> None:
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    # GROQ_API_KEY is not set in the test environment — must be reported
    # truthfully as not configured, never fabricated as available.
    assert response.json()["llm_configured"] is False
