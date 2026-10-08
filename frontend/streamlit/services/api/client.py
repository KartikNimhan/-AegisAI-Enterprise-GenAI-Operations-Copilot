"""The one place every HTTP call to the AegisAI backend goes through.

UI code (pages, components) never calls `httpx` directly — every call is
normalized into a parsed JSON body or a `BackendError`, so a page only
ever has to handle one exception type, never raw network/timeout/HTTP
exceptions or a Python traceback. The frontend is an untrusted client:
this module only ever talks to `AEGIS_BACKEND_URL` (configurable, never a
URL a user can type into the UI — see docs/architecture/decisions/
011-copilot-ui-architecture.md, "Security boundaries").
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BACKEND_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0


class BackendError(Exception):
    """Raised for any backend call failure. `code` is the backend's own
    error code (`not_found`, `validation_error`, `service_unavailable`,
    ...) when the backend responded with its structured error envelope
    (see `app.core.exceptions`), or a frontend-assigned one
    (`timeout`/`network_error`/`malformed_response`) when it didn't
    respond at all."""

    def __init__(
        self, message: str, *, code: str = "unknown_error", status_code: int | None = None
    ) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def backend_url() -> str:
    return os.environ.get("AEGIS_BACKEND_URL", DEFAULT_BACKEND_URL)


def _timeout_seconds() -> float:
    raw = os.environ.get("AEGIS_BACKEND_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _parse_error(response: httpx.Response) -> BackendError:
    try:
        payload = response.json()
        detail = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = detail.get("message") or f"The backend returned HTTP {response.status_code}"
        code = detail.get("code", "http_error")
    except ValueError:
        message = f"The backend returned HTTP {response.status_code}"
        code = "http_error"
    return BackendError(message, code=code, status_code=response.status_code)


def request_json(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    files: dict | None = None,
    params: dict | None = None,
    ok_status_codes: tuple[int, ...] | None = None,
) -> Any:
    """Makes one request and returns the parsed JSON body (`None` for an
    empty, e.g. 204, response). `ok_status_codes` overrides "any 2xx" for
    an endpoint where a non-2xx status is itself meaningful data to parse
    (e.g. `/health/ready`'s 503 "degraded" body), not a failure."""
    url = f"{backend_url()}{path}"
    try:
        with httpx.Client(timeout=_timeout_seconds()) as client:
            response = client.request(method, url, json=json, files=files, params=params)
    except httpx.TimeoutException as exc:
        raise BackendError(
            "The backend did not respond in time. Please try again.", code="timeout"
        ) from exc
    except httpx.HTTPError as exc:
        raise BackendError(
            "Could not reach the backend. Check that it is running.", code="network_error"
        ) from exc

    allowed = ok_status_codes or tuple(range(200, 300))
    if response.status_code not in allowed:
        raise _parse_error(response)

    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise BackendError(
            "The backend returned an unexpected response.", code="malformed_response"
        ) from exc
