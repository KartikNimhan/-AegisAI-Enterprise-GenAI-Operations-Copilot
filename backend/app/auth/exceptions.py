"""Internal authentication errors.

Each carries a short machine-readable `reason` used only for server-side
logging. `app.core.security` maps them to the generic public responses
(401 / 403 / 503) — the reason is never returned to the caller.
"""

from __future__ import annotations


class AuthError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class InvalidTokenError(AuthError):
    """The token is malformed, unsigned/wrongly signed, expired, or has wrong claims."""


class AuthKeysUnavailableError(AuthError):
    """The signing keys could not be fetched and none are cached."""


class IdentityNotLinkedError(AuthError):
    """A valid token whose (issuer, subject) is not linked to any internal user."""


class AccountDisabledError(AuthError):
    """The linked user, or the user's organization, is disabled."""
