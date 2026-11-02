"""Every API response is marked nosniff and not cacheable, including errors.

Responses carry conversations, documents and memories: a shared or browser cache must never
keep them, and a JSON body must never be content-sniffed into something else.
"""

from __future__ import annotations

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.middleware import SECURITY_HEADERS
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    application = create_app(
        Settings(_env_file=None, debug=True, environment="local", max_request_body_bytes=1024)  # type: ignore[call-arg]
    )

    async def boom() -> None:
        raise RuntimeError("synthetic")

    async def own_cache_policy(response: Response) -> dict:
        response.headers["Cache-Control"] = "public, max-age=60"
        return {"ok": True}

    application.add_api_route("/__boom", boom)
    application.add_api_route("/__cached", own_cache_policy)
    return TestClient(application, raise_server_exceptions=False)


def assert_hardened(response) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_a_normal_response_is_hardened(client: TestClient) -> None:
    assert_hardened(client.get("/health"))


def test_error_responses_are_hardened(client: TestClient) -> None:
    assert_hardened(client.post("/api/v1/chat/completions", json={}))  # 422
    assert_hardened(client.get("/api/v1/does-not-exist"))  # 404
    assert_hardened(client.post("/api/v1/chat/completions", content=b"x" * 5000))  # 413


def test_an_unhandled_500_is_hardened(client: TestClient) -> None:
    response = client.get("/__boom")

    assert response.status_code == 500
    assert_hardened(response)
    assert response.headers["x-request-id"]


def test_a_route_that_chooses_its_own_caching_keeps_it(client: TestClient) -> None:
    response = client.get("/__cached")

    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_the_header_set_is_what_the_docs_promise() -> None:
    assert SECURITY_HEADERS == {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
