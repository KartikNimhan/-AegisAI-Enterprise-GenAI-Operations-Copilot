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


def test_the_upload_route_gets_its_own_larger_limit(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents", files={"file": ("a.txt", b"z" * (LIMIT * 3), "text/plain")}
    )

    assert response.status_code != 413  # within the upload route's own (larger) limit


@pytest.mark.parametrize(
    "content_type",
    ["multipart/form-data; boundary=x", "MULTIPART/form-data", "multipart/mixed"],
)
def test_claiming_to_be_multipart_does_not_skip_the_limit(
    client: TestClient, content_type: str
) -> None:
    # Regression: any request labelled multipart used to be exempt, so a JSON route would read a
    # body of any size. Only the upload route has a different limit, and it is chosen by path.
    response = client.post(
        "/__echo", content=b"A" * (LIMIT * 50), headers={"content-type": content_type}
    )

    assert response.status_code == 413


def test_a_multipart_body_to_a_json_route_is_cut_off_even_without_a_length(
    client: TestClient,
) -> None:
    def body() -> Iterator[bytes]:
        for _ in range(100):
            yield b"y" * 1024

    response = client.post(
        "/__echo", content=body(), headers={"content-type": "multipart/form-data; boundary=x"}
    )

    assert response.status_code == 413


def test_the_upload_route_limit_is_the_upload_size_plus_framing() -> None:
    from app.core.middleware import MULTIPART_OVERHEAD_BYTES

    upload_limit = 4096
    application = create_app(
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            debug=True,
            environment="local",
            max_request_body_bytes=LIMIT,
            document_max_upload_size_bytes=upload_limit,
        )
    )
    oversized = b"z" * (upload_limit + MULTIPART_OVERHEAD_BYTES + 1)

    response = TestClient(application).post(
        "/api/v1/documents", files={"file": ("a.txt", oversized, "text/plain")}
    )

    assert response.status_code == 413  # bounded before the upload is spooled anywhere


def test_only_a_post_to_the_upload_path_gets_the_upload_limit() -> None:
    from app.core.middleware import BodySizeLimitMiddleware

    middleware = BodySizeLimitMiddleware(
        None,  # type: ignore[arg-type]
        max_body_bytes=10,
        upload_limits={"/api/v1/documents": 1000},
    )

    assert middleware.limit_for({"method": "POST", "path": "/api/v1/documents"}) == 1000
    assert middleware.limit_for({"method": "PUT", "path": "/api/v1/documents"}) == 10
    assert middleware.limit_for({"method": "POST", "path": "/api/v1/documents/x"}) == 10
    assert middleware.limit_for({"method": "POST", "path": "/api/v1/chat/completions"}) == 10


def test_a_get_request_is_unaffected(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_the_limit_is_validated() -> None:
    for bad in (0, 100, 10**10):
        with pytest.raises(ValueError):
            Settings(_env_file=None, debug=False, max_request_body_bytes=bad)  # type: ignore[call-arg]
