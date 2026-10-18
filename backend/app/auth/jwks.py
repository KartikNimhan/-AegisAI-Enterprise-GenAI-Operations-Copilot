"""Signing-key lookup for token verification.

Wraps PyJWT's `PyJWKClient` (cached key set, `kid` matching, a refresh on an
unknown `kid` limited by a cooldown). That client does blocking HTTP via
`urllib` (it refuses redirects and non-http(s) schemes), so every call is run
in a worker thread to keep the event loop free. There is no stale-key grace:
when the cache has expired and the key endpoint is down, verification fails
closed (the caller maps `AuthKeysUnavailableError` to 503).
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import jwt

from app.auth.exceptions import AuthKeysUnavailableError, InvalidTokenError
from app.config import Settings


class SigningKeyProvider(Protocol):
    async def get_signing_key(self, token: str) -> Any:
        """Returns the public key to verify `token` with."""
        ...


class _KeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str | bytes) -> Any: ...


class JwksSigningKeyProvider:
    def __init__(self, client: _KeyClient) -> None:
        self._client = client

    @classmethod
    def create(
        cls, *, jwks_url: str, cache_seconds: int, timeout: float, min_refresh_seconds: float
    ) -> JwksSigningKeyProvider:
        return cls(
            jwt.PyJWKClient(
                jwks_url,
                cache_jwk_set=True,
                lifespan=cache_seconds,
                timeout=timeout,
                cooldown_duration=min_refresh_seconds,
            )
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> JwksSigningKeyProvider:
        assert settings.auth_jwks_url, "auth_jwks_url must be configured"
        return cls.create(
            jwks_url=settings.auth_jwks_url,
            cache_seconds=settings.auth_jwks_cache_seconds,
            timeout=settings.auth_jwks_timeout_seconds,
            min_refresh_seconds=settings.auth_jwks_min_refresh_seconds,
        )

    async def get_signing_key(self, token: str) -> Any:
        try:
            signing_key = await asyncio.to_thread(self._client.get_signing_key_from_jwt, token)
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthKeysUnavailableError("jwks_unreachable") from exc
        except jwt.PyJWKClientError as exc:
            # Includes "no key matches this kid" (after the client's own
            # rate-limited refresh) and an unusable key-set response.
            raise InvalidTokenError("unknown_signing_key") from exc
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed_token") from exc
        return signing_key.key
