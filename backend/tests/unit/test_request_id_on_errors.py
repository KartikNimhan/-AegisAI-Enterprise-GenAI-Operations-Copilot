"""Every response carries X-Request-ID, including an unhandled-exception 500."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_unhandled_500_has_request_id_header_matching_body() -> None:
    app = create_app(Settings(_env_file=None, debug=True, environment="local"))  # type: ignore[call-arg]

    async def boom() -> None:
        raise RuntimeError("synthetic")

    app.add_api_route("/__boom", boom)
    response = TestClient(app, raise_server_exceptions=False).get(
        "/__boom", headers={"X-Request-ID": "abc-123"}
    )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "abc-123"
    assert response.json()["error"]["request_id"] == "abc-123"
