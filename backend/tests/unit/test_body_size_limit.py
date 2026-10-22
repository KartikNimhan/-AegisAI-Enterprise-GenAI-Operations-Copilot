"""Request bodies are bounded before they are parsed (non-upload requests)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

LIMIT = 2048


@pytest.fixture
def client() -> TestClient:
    application = create_app(
        Settings(_env_file=None, debug=True, environment="local", max_request_body_bytes=LIMIT)  # type: ignore[call-arg]
    )

    async def echo(request: Request) -> dict:
        return {"size": len(await request.body())}

    application.add_api_route("/__echo", echo, methods=["POST"])
    return TestClient(application)


def test_a_body_within_the_limit_passes(client: TestClient) -> None:
    response = client.post("/__echo", content=b"x" * LIMIT)

    assert response.status_code == 200 and response.json() == {"size": LIMIT}


def test_a_declared_length_over_the_limit_is_refused_with_the_standard_envelope(
    client: TestClient,
) -> None:
    response = client.post("/__echo", content=b"x" * (LIMIT + 1), headers={"X-Request-ID": "req-1"})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.json()["error"]["request_id"] == "req-1"
    assert response.headers["x-request-id"] == "req-1"


def test_a_chunked_body_with_no_length_is_cut_off_at_the_limit(client: TestClient) -> None:
    def body() -> Iterator[bytes]:
        for _ in range(100):  # 100 KiB, no Content-Length
            yield b"y" * 1024

    response = client.post("/__echo", content=body())

    assert response.status_code == 413


def test_the_real_endpoints_refuse_a_huge_json_body_before_validating_it(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/chat/completions", json={"message": "m" * 5000})

    assert response.status_code == 413  # not 401/422: the body was never parsed


def test_multipart_uploads_are_exempt_from_this_limit(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents", files={"file": ("a.txt", b"z" * (LIMIT * 3), "text/plain")}
    )

    assert response.status_code != 413  # the upload endpoint applies its own limit


def test_a_get_request_is_unaffected(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_the_limit_is_validated() -> None:
    for bad in (0, 100, 10**10):
        with pytest.raises(ValueError):
            Settings(_env_file=None, debug=False, max_request_body_bytes=bad)  # type: ignore[call-arg]
