"""Route inventory: every operation the API exposes either requires
authentication or is in the EXPLICIT public list below. A newly added route
that forgets authentication fails this test — and nothing is "temporarily
public" (no A2A task exemption).

Behavioral on purpose: each operation in the OpenAPI schema is called with no
credentials. (FastAPI's included-router structure is private framework
internals, so inspecting dependencies directly would be fragile.)"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# The complete list of unauthenticated operations. Changing it is a security
# decision — update the M12 plan/ADR at the same time.
PUBLIC_OPERATIONS = {
    ("GET", "/health"),  # liveness probe (Docker/Kubernetes)
    ("GET", "/health/ready"),  # readiness probe (Kubernetes)
    ("GET", "/.well-known/agent-card.json"),  # A2A convention; non-sensitive metadata
    ("GET", "/api/v1/agents/research/card"),  # public Agent Cards, fetched
    ("GET", "/api/v1/agents/document/card"),  # without credentials by A2AClient
    ("GET", "/api/v1/agents/analyst/card"),
}

# Framework-generated documentation routes, present only in local development.
LOCAL_DOCS_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

A2A_TASK_ROUTES = [
    "/api/v1/agents/research/tasks",
    "/api/v1/agents/document/tasks",
    "/api/v1/agents/analyst/tasks",
]


def _is_unauthorized(response) -> bool:
    return response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


def test_every_operation_requires_authentication_except_the_public_list(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _up(*args: object, **kwargs: object) -> bool:
        return True

    # Keep the public readiness probe from touching a real database/Redis.
    monkeypatch.setattr("app.api.v1.health.check_database", _up)
    monkeypatch.setattr("app.api.v1.health.check_redis", _up)

    unprotected: list[str] = []
    public_seen: set[tuple[str, str]] = set()
    checked = 0
    for path, item in app.openapi()["paths"].items():
        for method in item:
            if method not in HTTP_METHODS:
                continue
            checked += 1
            url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
            response = anon_client.request(method.upper(), url)
            operation = (method.upper(), path)
            if operation in PUBLIC_OPERATIONS:
                public_seen.add(operation)
                if _is_unauthorized(response):
                    unprotected.append(f"{operation} should be public but answered 401")
            elif not _is_unauthorized(response):
                unprotected.append(
                    f"{operation} answered {response.status_code} without credentials"
                )

    assert checked > 20, "the schema walk found suspiciously few operations"
    assert unprotected == []
    assert public_seen == PUBLIC_OPERATIONS


@pytest.mark.parametrize("path", A2A_TASK_ROUTES)
def test_a2a_task_endpoints_are_not_public(anon_client: TestClient, path: str) -> None:
    response = anon_client.post(path, json={"question": "q"})

    assert _is_unauthorized(response)


def test_no_unexpected_non_schema_routes_exist() -> None:
    """Plain Starlette routes bypass the OpenAPI walk above; only the
    framework's own documentation routes may exist."""
    plain = {route.path for route in app.routes if type(route).__name__ == "Route"}  # type: ignore[attr-defined]

    assert plain <= LOCAL_DOCS_ROUTES
