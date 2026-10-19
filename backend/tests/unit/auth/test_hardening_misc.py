"""Request-id full-string matching (M12 review L4) and the quiet, generic
behavior of an unconfigured API (L7)."""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.core.security as security_module
import app.main as main_module
from app.config import Settings, get_settings
from app.main import app, create_app

ME = "/api/v1/auth/me"


class _Recorder:
    """Stands in for a structlog logger and remembers (level, event) pairs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Any:
        return lambda event, **kw: self.calls.append((level, event, kw))

    def levels_for(self, event: str) -> list[str]:
        return [level for level, name, _ in self.calls if name == event]


async def _asgi_request_id(raw_header_value: bytes | None) -> str:
    """Drives the ASGI app directly: HTTP clients refuse to send a newline in a
    header value, but a proxy or a buggy server could still hand one to us."""
    messages: list[MutableMapping[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        messages.append(message)

    headers = [(b"x-request-id", raw_header_value)] if raw_header_value is not None else []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    return dict(start["headers"])[b"x-request-id"].decode("latin-1")


@pytest.mark.parametrize(
    "value",
    [b"abc\n", b"abc\r\n", b"\nabc", b"abc\nX-Injected: 1", b"abc\r", b"ab\x00c", b"abc "],
)
async def test_a_request_id_containing_a_newline_or_control_character_is_replaced(
    value: bytes,
) -> None:
    returned = await _asgi_request_id(value)

    assert returned != value.decode("latin-1")
    assert "\n" not in returned and "\r" not in returned
    uuid.UUID(returned)  # a freshly generated id


async def test_a_clean_request_id_is_still_echoed_and_a_missing_one_generated() -> None:
    assert await _asgi_request_id(b"req-1.2_3") == "req-1.2_3"
    uuid.UUID(await _asgi_request_id(None))


# -- L7: the unconfigured case is quiet and generic -----------------------------------


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]


def _unconfigured_settings() -> Settings:
    return _settings(auth_issuer=None, auth_audience=None, auth_jwks_url=None)


def test_unconfigured_authentication_does_not_log_an_error_per_request(
    real_auth: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(security_module, "logger", recorder)
    app.dependency_overrides[get_settings] = _unconfigured_settings
    try:
        with TestClient(app) as client:
            responses = [client.get(ME) for _ in range(5)]
            responses.append(client.get(ME, headers={"Authorization": "Bearer anything"}))
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert {r.status_code for r in responses} == {503}
    assert "error" not in recorder.levels_for("auth.not_configured")
    assert "warning" not in recorder.levels_for("auth.not_configured")


def test_the_public_503_for_an_unconfigured_api_reveals_no_configuration_details(
    real_auth: None,
) -> None:
    app.dependency_overrides[get_settings] = _unconfigured_settings
    try:
        with TestClient(app) as client:
            response = client.get(ME)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    body = response.text
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"
    assert response.json()["error"]["message"] == "Authentication is temporarily unavailable"
    for leak in (
        "AUTH_ISSUER",
        "AUTH_AUDIENCE",
        "AUTH_JWKS_URL",
        "not configured",
        "unconfigured",
        "issuer",
        "jwks",
        "audience",
        "environment",
    ):
        assert leak.lower() not in body.lower(), leak


def test_the_misconfiguration_is_logged_once_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(main_module, "logger", recorder)

    create_app(_unconfigured_settings())

    assert recorder.levels_for("auth.not_configured") == ["error"]


def test_a_configured_application_logs_no_startup_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(main_module, "logger", recorder)
    configured = _settings(
        auth_issuer="https://idp.example.test/realms/aegis",
        auth_audience="aegisai-api",
        auth_jwks_url="https://idp.example.test/realms/aegis/protocol/openid-connect/certs",
    )

    create_app(configured)

    assert recorder.levels_for("auth.not_configured") == []
