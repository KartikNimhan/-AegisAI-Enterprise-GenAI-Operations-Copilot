"""Signing-key lookup for token verification.

Wraps PyJWT's `PyJWKClient` (cached key set, `kid` matching, a refresh on an
unknown `kid` limited by a cooldown). That client does blocking HTTP via
`urllib` (it refuses redirects and non-http(s) schemes), so every call is run
in a worker thread to keep the event loop free. There is no stale-key grace:
when the cache has expired and the key endpoint is down, verification fails
closed.

Hardening (M12 review findings M1/M2):
- **Circuit breaker.** After a failed or malformed key-set fetch, further
  fetches are refused for `failure_cooldown_seconds`, so an outage costs at most
  one network attempt per window instead of one per request (the underlying
  client holds a lock while fetching, which used to serialize every request
  behind a full timeout). The breaker sits on the *fetch*, so lookups that the
  cache can answer (a known `kid` while the cached key set is valid) keep working.
- **Bounded concurrency.** At most `MAX_CONCURRENT_KEY_LOOKUPS` lookups occupy
  worker threads at once, so authentication cannot starve the shared executor
  (file storage uses it too).
- **Failure classification.** A key endpoint that is unreachable, returns
  something that is not a usable key set (HTML, non-JSON, an empty set, a key
  that cannot be parsed, no signing keys) is *infrastructure* failure ->
  `AuthKeysUnavailableError` (503). Only "no published key matches this token's
  `kid`" and an unparsable token are *user* problems -> `InvalidTokenError` (401).
  "Unknown `kid`" is decided from the data (the key set is usable and does not
  contain the `kid`) and signalled with `UnknownSigningKeyError`; PyJWT's
  exception message text is never inspected.
- **No lingering unusable key set.** A response that parses but holds no signing
  key (only `use: enc` keys, or keys without a `kid`) is cached by PyJWT before it
  is checked, and PyJWT would then keep failing every lookup from that cache
  until it expired, without ever refetching. It is discarded and the breaker is
  tripped instead, so the next fetch after the cooldown can recover.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Protocol

import jwt

from app.auth.exceptions import AuthKeysUnavailableError, InvalidTokenError
from app.config import Settings

MAX_CONCURRENT_KEY_LOOKUPS = 4


class UnknownSigningKeyError(jwt.PyJWKClientError):
    """The key set is healthy but publishes no signing key for the token's `kid`
    (or the token has none). Raised only by `GuardedJWKClient`."""


class SigningKeyProvider(Protocol):
    async def get_signing_key(self, token: str) -> Any:
        """Returns the public key to verify `token` with."""
        ...


class _KeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str | bytes) -> Any: ...


class GuardedJWKClient(jwt.PyJWKClient):
    """`PyJWKClient` plus a failure circuit breaker and malformed-response
    handling around every network fetch / key-set parse."""

    def __init__(self, uri: str, *, failure_cooldown_seconds: float, **kwargs: Any) -> None:
        super().__init__(uri, **kwargs)
        self._failure_cooldown = failure_cooldown_seconds
        self._failed_until = 0.0
        self._state_lock = threading.Lock()

    # -- circuit breaker ---------------------------------------------------------
    def _circuit_is_open(self) -> bool:
        with self._state_lock:
            return time.monotonic() < self._failed_until

    def _trip(self) -> None:
        if self._failure_cooldown > 0:
            with self._state_lock:
                self._failed_until = time.monotonic() + self._failure_cooldown

    # -- network seam (overridden in tests) ---------------------------------------
    def _fetch_remote(self) -> Any:
        return super().fetch_data()

    def fetch_data(self) -> Any:
        if self._circuit_is_open():
            raise jwt.PyJWKClientConnectionError("key-set fetch suppressed after a recent failure")
        try:
            return self._fetch_remote()
        except jwt.PyJWKClientConnectionError:
            self._trip()
            raise
        except (jwt.PyJWKClientError, jwt.PyJWKSetError, ValueError) as exc:
            # Not a key set at all (HTML error page, non-object JSON, ...).
            self._trip()
            raise jwt.PyJWKClientConnectionError("unusable key endpoint response") from exc

    def get_jwk_set(self, refresh: bool = False) -> Any:
        try:
            return super().get_jwk_set(refresh)
        except jwt.PyJWKClientConnectionError:
            raise
        except (jwt.PyJWKClientError, jwt.PyJWKSetError, ValueError, KeyError, TypeError) as exc:
            # A response that parsed as JSON but is not a usable JWK Set (empty,
            # or a key PyJWT cannot construct).
            self._trip()
            raise jwt.PyJWKClientConnectionError("unusable key set") from exc

    def _discard_cached_key_set(self) -> None:
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(None)  # PyJWT's documented way to clear the cache

    def get_signing_keys(self, refresh: bool = False) -> list[jwt.PyJWK]:
        try:
            return super().get_signing_keys(refresh)
        except jwt.PyJWKClientConnectionError:
            raise
        except jwt.PyJWKClientError as exc:
            # `get_jwk_set` (above) already turns every fetch and parse failure
            # into a connection error, so the only error left here is "the set
            # parsed, but holds no signing key". PyJWT has cached that set by
            # now; drop it and open the breaker so the next fetch (after the
            # cooldown) can pick up a corrected key set instead of failing from
            # the cache for its whole lifetime.
            self._trip()
            self._discard_cached_key_set()
            raise jwt.PyJWKClientConnectionError("key set has no usable signing keys") from exc

    def get_signing_key(self, kid: str) -> jwt.PyJWK:
        try:
            return super().get_signing_key(kid)
        except jwt.PyJWKClientConnectionError:
            raise
        except jwt.PyJWKClientError as exc:
            # PyJWT reports "no key matches" with the same base exception it uses
            # for other problems, so do not trust the exception: decide from the
            # data. The key set must be usable (otherwise this raises a connection
            # error) and must not contain the `kid`. If it does contain it, PyJWT
            # failed for some other reason and the caller must not see a 401.
            published = self.get_signing_keys()
            if any(key.key_id == kid for key in published):
                raise
            raise UnknownSigningKeyError("no published signing key matches this kid") from exc


class JwksSigningKeyProvider:
    def __init__(
        self, client: _KeyClient, *, max_concurrent: int = MAX_CONCURRENT_KEY_LOOKUPS
    ) -> None:
        self._client = client
        self._slots = asyncio.Semaphore(max_concurrent)

    @classmethod
    def create(
        cls,
        *,
        jwks_url: str,
        cache_seconds: int,
        timeout: float,
        min_refresh_seconds: float,
        failure_cooldown_seconds: float = 5.0,
    ) -> JwksSigningKeyProvider:
        return cls(
            GuardedJWKClient(
                jwks_url,
                failure_cooldown_seconds=failure_cooldown_seconds,
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
            failure_cooldown_seconds=settings.auth_jwks_failure_cooldown_seconds,
        )

    async def get_signing_key(self, token: str) -> Any:
        async with self._slots:
            try:
                signing_key = await asyncio.to_thread(self._client.get_signing_key_from_jwt, token)
            except jwt.PyJWKClientConnectionError as exc:
                raise AuthKeysUnavailableError("jwks_unreachable") from exc
            except UnknownSigningKeyError as exc:
                raise InvalidTokenError("unknown_signing_key") from exc
            except jwt.PyJWKClientError as exc:
                # Anything else from the key client is not the caller's fault.
                raise AuthKeysUnavailableError("jwks_unusable") from exc
            except jwt.PyJWKSetError as exc:
                raise AuthKeysUnavailableError("jwks_unusable") from exc
            except jwt.PyJWTError as exc:
                # An unparsable token header and similar: the caller's problem.
                raise InvalidTokenError("malformed_token") from exc
            except Exception as exc:  # noqa: BLE001 - anything else came from the key set
                raise AuthKeysUnavailableError("jwks_unusable") from exc
        return signing_key.key
