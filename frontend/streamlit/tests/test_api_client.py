"""Unit tests for `services.api.client.request_json` — the one place
every backend call is normalized, tested directly against a mocked
`httpx` transport, no real network.
"""

from __future__ import annotations

import httpx
import pytest

from services.api import client as client_module
from services.api.client import BackendError, request_json


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _factory(*, timeout: float) -> httpx.Client:
        return real_client(transport=transport, timeout=timeout)

    monkeypatch.setattr(client_module.httpx, "Client", _factory)


def test_successful_response_returns_parsed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    _install_transport(monkeypatch, handler)

    result = request_json("GET", "/health")

    assert result == {"status": "ok"}


def test_error_envelope_is_parsed_into_a_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"code": "not_found", "message": "Document not found"}}
        )

    _install_transport(monkeypatch, handler)

    with pytest.raises(BackendError) as exc_info:
        request_json("GET", "/api/v1/documents/does-not-exist")

    assert exc_info.value.code == "not_found"
    assert "Document not found" in str(exc_info.value)


def test_network_failure_is_wrapped_as_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection failure", request=request)

    _install_transport(monkeypatch, handler)

    with pytest.raises(BackendError) as exc_info:
        request_json("GET", "/health")

    assert exc_info.value.code == "network_error"


def test_timeout_is_wrapped_as_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    _install_transport(monkeypatch, handler)

    with pytest.raises(BackendError) as exc_info:
        request_json("GET", "/health")

    assert exc_info.value.code == "timeout"


def test_an_expected_non_2xx_status_is_accepted_when_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"status": "degraded"})

    _install_transport(monkeypatch, handler)

    result = request_json("GET", "/health/ready", ok_status_codes=(200, 503))

    assert result == {"status": "degraded"}


def test_malformed_json_response_is_a_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    _install_transport(monkeypatch, handler)

    with pytest.raises(BackendError) as exc_info:
        request_json("GET", "/health")

    assert exc_info.value.code == "malformed_response"
