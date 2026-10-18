"""API documentation is served only in local development; client-supplied
request ids are only trusted when short and made of safe characters."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, create_app


def _settings(environment: str) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment=environment,
        auth_issuer="https://idp.example.test/realms/aegis",
        auth_audience="aegisai-api",
        auth_jwks_url="https://idp.example.test/realms/aegis/protocol/openid-connect/certs",
    )


@pytest.mark.parametrize("environment", ["docker", "kubernetes", "production", "staging"])
def test_docs_and_schema_are_not_served_outside_local(environment: str) -> None:
    client = TestClient(create_app(_settings(environment)))  # no lifespan: no model warm-up

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path
    assert client.get("/health").status_code == 200  # probes unaffected


def test_docs_and_schema_are_served_in_local_development() -> None:
    client = TestClient(create_app(_settings("local")))

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_a_safe_request_id_is_echoed() -> None:
    response = TestClient(app).get("/health", headers={"X-Request-ID": "req-123.abc_DEF"})

    assert response.headers["x-request-id"] == "req-123.abc_DEF"


@pytest.mark.parametrize(
    "unsafe",
    ["x" * 65, "has space", "<script>alert(1)</script>", "semi;colon", "new\tline", "é"],
)
def test_an_unsafe_request_id_is_replaced_with_a_fresh_one(unsafe: str) -> None:
    try:
        response = TestClient(app).get("/health", headers={"X-Request-ID": unsafe})
    except UnicodeEncodeError:
        pytest.skip("the HTTP client cannot even send this header value")

    returned = response.headers["x-request-id"]
    assert returned != unsafe
    uuid.UUID(returned)  # a freshly generated UUID


def test_a_missing_request_id_is_generated() -> None:
    returned = TestClient(app).get("/health").headers["x-request-id"]

    uuid.UUID(returned)
