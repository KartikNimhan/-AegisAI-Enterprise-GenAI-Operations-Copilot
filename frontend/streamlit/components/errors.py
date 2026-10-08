"""Maps a `BackendError` into a user-facing message — never a raw
exception string, stack trace, or internal implementation detail.

A structured backend error (`not_found`, `validation_error`,
`service_unavailable`, ...) already carries a safe, user-facing message
at the backend layer (see `app.core.exceptions`) — it is surfaced
directly. A connectivity-level failure (`timeout`/`network_error`/
`malformed_response`, assigned by the frontend client itself, never the
backend) gets one of the messages below.
"""

from __future__ import annotations

from services.api.client import BackendError

_FRONTEND_MESSAGES = {
    "timeout": "The backend did not respond in time. Please try again.",
    "network_error": "Unable to reach the backend. Check that it is running.",
    "malformed_response": "The backend returned an unexpected response.",
}


def friendly_message(exc: BackendError) -> str:
    return _FRONTEND_MESSAGES.get(exc.code, str(exc))
