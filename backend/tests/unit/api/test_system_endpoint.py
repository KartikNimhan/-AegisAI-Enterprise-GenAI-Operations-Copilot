"""Unit tests for GET /api/v1/system/status.

Database/redis connectivity checks are monkeypatched (same pattern as
tests/unit/test_health.py) — deterministic regardless of whether a real
Postgres/Redis is running.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_principal
from app.domain.enums.user_role import UserRole
from app.main import app

from ...conftest import DEFAULT_TEST_PRINCIPAL


@pytest.fixture
def signed_in_as_admin(_default_authentication: None) -> Iterator[None]:
    """The status page is administrator-only, so these tests sign in as one (the default test
    principal is an ordinary member)."""
    admin = replace(DEFAULT_TEST_PRINCIPAL, role=UserRole.ADMIN)
    app.dependency_overrides[get_current_principal] = lambda: admin
    yield


pytestmark_admin = pytest.mark.usefixtures("signed_in_as_admin")


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False


@pytestmark_admin
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


@pytestmark_admin
def test_status_reports_unavailable_when_database_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.v1.system.check_database", _async_false)
    monkeypatch.setattr("app.api.v1.system.check_redis", _async_true)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    assert response.json()["database"] == "unavailable"


@pytestmark_admin
def test_status_never_claims_llm_configured_without_a_key(client: TestClient) -> None:
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    # GROQ_API_KEY is not set in the test environment — must be reported
    # truthfully as not configured, never fabricated as available.
    assert response.json()["llm_configured"] is False


def test_a_member_is_forbidden_and_learns_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page reveals infrastructure (the trusted agent URLs, the MCP server name, database and
    Redis state), so an ordinary member gets the same generic 403 as any other admin-only route."""
    monkeypatch.setattr("app.api.v1.system.check_database", _async_true)
    monkeypatch.setattr("app.api.v1.system.check_redis", _async_true)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 403
    body = response.text
    assert "aegisai-internal" not in body
    assert "localhost:8000" not in body
