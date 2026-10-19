"""Hardening of the key lookup (M12 review findings M1/M2): malformed key-set
responses are a controlled 503, a failure opens a short circuit breaker so an
outage costs one network attempt per window (not one per request), concurrent
failures collapse, and worker-thread use is bounded. User-token problems stay
distinct from unavailable key infrastructure."""

from __future__ import annotations

import asyncio
import io
import threading
import time
import urllib.request
from contextlib import contextmanager
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.exceptions import AuthKeysUnavailableError, InvalidTokenError
from app.auth.jwks import GuardedJWKClient, JwksSigningKeyProvider
from app.auth.tokens import TokenVerifier
from app.core.security import get_token_verifier
from app.main import app

from ...auth_fixtures import (
    AUDIENCE,
    ISSUER,
    JWKS_URL,
    SigningKey,
    generate_signing_key,
    jwks_for,
    mint_token,
)


@pytest.fixture(scope="module")
def key() -> SigningKey:
    return generate_signing_key("sig-1")


@pytest.fixture(scope="module")
def other_key() -> SigningKey:
    return generate_signing_key("not-published")


class ScriptedClient(GuardedJWKClient):
    """The real guarded client with only the network call scripted."""

    def __init__(
        self, *, cooldown: float = 5.0, delay: float = 0.0, min_refresh: float = 0
    ) -> None:
        super().__init__(
            JWKS_URL,
            failure_cooldown_seconds=cooldown,
            cache_jwk_set=True,
            lifespan=600,
            timeout=5,
            cooldown_duration=min_refresh,
        )
        self.fetches = 0
        self.delay = delay
        self.behaviour: Any = None  # a JWK set dict to return, or an exception to raise
        self._count_lock = threading.Lock()

    def _fetch_remote(self) -> Any:
        with self._count_lock:
            self.fetches += 1
        if self.delay:
            time.sleep(self.delay)
        if isinstance(self.behaviour, BaseException):
            raise self.behaviour
        return self.behaviour


def _down() -> jwt.PyJWKClientConnectionError:
    return jwt.PyJWKClientConnectionError("simulated outage")


@contextmanager
def _key_endpoint_returns(body: bytes):
    """Fakes only the HTTP layer underneath the REAL PyJWT fetch/parse code."""
    original = urllib.request.build_opener
    opens: list[int] = []

    class _Opener:
        def open(self, request: Any, timeout: Any = None) -> Any:
            opens.append(1)

            @contextmanager
            def response():
                yield io.BytesIO(body)

            return response()

    urllib.request.build_opener = lambda *a, **k: _Opener()  # type: ignore[assignment]
    try:
        yield opens
    finally:
        urllib.request.build_opener = original


def _real_provider(cooldown: float = 5.0) -> JwksSigningKeyProvider:
    return JwksSigningKeyProvider.create(
        jwks_url="https://idp.example.test/certs",
        cache_seconds=600,
        timeout=5,
        min_refresh_seconds=0,
        failure_cooldown_seconds=cooldown,
    )


# -- M2: malformed key-set responses ------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body>502 Bad Gateway</body></html>",  # a proxy error page
        b"not json at all",
        b"",  # empty body
        b"[]",  # JSON, but not an object
        b"{}",  # no 'keys'
        b'{"keys": []}',  # empty key set
        b'{"keys": [{"kty": "oct"}]}',  # a key PyJWT cannot construct
        b'{"keys": "nope"}',
    ],
)
async def test_a_malformed_key_endpoint_response_is_a_controlled_503(
    key: SigningKey, body: bytes
) -> None:
    provider = _real_provider()

    with _key_endpoint_returns(body), pytest.raises(AuthKeysUnavailableError):
        await provider.get_signing_key(mint_token(key))


async def test_a_key_set_with_no_signing_keys_is_unavailable_infrastructure(
    key: SigningKey,
) -> None:
    only_encryption_keys = {"keys": [jwks_for(key)["keys"][-1]]}
    assert only_encryption_keys["keys"][0]["use"] == "enc"
    import json

    with (
        _key_endpoint_returns(json.dumps(only_encryption_keys).encode()),
        pytest.raises(AuthKeysUnavailableError),
    ):
        await _real_provider().get_signing_key(mint_token(key))


async def test_a_good_key_set_works_and_an_unknown_kid_is_the_users_problem(
    key: SigningKey, other_key: SigningKey
) -> None:
    import json

    body = json.dumps(jwks_for(key)).encode()
    provider = _real_provider()

    with _key_endpoint_returns(body):
        assert await provider.get_signing_key(mint_token(key)) is not None
        # A token naming a key that the (healthy) set does not publish: 401, not 503.
        with pytest.raises(InvalidTokenError) as info:
            await provider.get_signing_key(mint_token(other_key))

    assert info.value.reason == "unknown_signing_key"


async def test_an_unparsable_token_is_the_users_problem_even_when_keys_are_down(
    key: SigningKey,
) -> None:
    provider = _real_provider()

    with _key_endpoint_returns(b"<html>down</html>"), pytest.raises(InvalidTokenError):
        await provider.get_signing_key("not-a-jwt")


async def test_a_malformed_response_is_not_refetched_on_every_request(key: SigningKey) -> None:
    provider = _real_provider(cooldown=5.0)

    with _key_endpoint_returns(b"<html>502</html>") as opens:
        for _ in range(5):
            with pytest.raises(AuthKeysUnavailableError):
                await provider.get_signing_key(mint_token(key))

    assert len(opens) == 1


async def test_an_unexpected_error_from_the_key_client_is_unavailable_not_a_crash(
    key: SigningKey,
) -> None:
    class _Broken:
        def get_signing_key_from_jwt(self, token: Any) -> Any:
            raise RuntimeError("boom")

    with pytest.raises(AuthKeysUnavailableError) as info:
        await JwksSigningKeyProvider(_Broken()).get_signing_key(mint_token(key))

    assert info.value.reason == "jwks_unusable"


# -- M1: circuit breaker and concurrency ---------------------------------------------


async def test_a_failure_opens_the_breaker_and_later_lookups_do_not_touch_the_network(
    key: SigningKey,
) -> None:
    client = ScriptedClient(cooldown=60)
    client.behaviour = _down()
    provider = JwksSigningKeyProvider(client)

    for _ in range(5):
        with pytest.raises(AuthKeysUnavailableError):
            await provider.get_signing_key(mint_token(key))

    assert client.fetches == 1  # not 5


async def test_the_breaker_closes_after_the_cooldown_and_recovery_is_automatic(
    key: SigningKey,
) -> None:
    client = ScriptedClient(cooldown=0.15)
    client.behaviour = _down()
    provider = JwksSigningKeyProvider(client)
    with pytest.raises(AuthKeysUnavailableError):
        await provider.get_signing_key(mint_token(key))

    await asyncio.sleep(0.25)  # cooldown over
    client.behaviour = jwks_for(key)  # the identity provider is back

    assert await provider.get_signing_key(mint_token(key)) is not None
    assert await provider.get_signing_key(mint_token(key)) is not None
    assert client.fetches == 2  # one failed attempt, one successful; then cached


async def test_a_zero_cooldown_disables_the_breaker(key: SigningKey) -> None:
    client = ScriptedClient(cooldown=0)
    client.behaviour = _down()
    provider = JwksSigningKeyProvider(client)

    for _ in range(3):
        with pytest.raises(AuthKeysUnavailableError):
            await provider.get_signing_key(mint_token(key))

    assert client.fetches == 3


async def test_concurrent_requests_during_an_outage_collapse_into_one_attempt(
    key: SigningKey,
) -> None:
    """Before the fix N concurrent requests ran N serialized fetches, each a
    full timeout long (the client holds a lock while fetching)."""
    client = ScriptedClient(cooldown=60, delay=0.3)
    client.behaviour = _down()
    provider = JwksSigningKeyProvider(client)

    started = time.perf_counter()
    results = await asyncio.gather(
        *(provider.get_signing_key(mint_token(key)) for _ in range(8)), return_exceptions=True
    )
    elapsed = time.perf_counter() - started

    assert all(isinstance(r, AuthKeysUnavailableError) for r in results)
    assert client.fetches == 1
    assert elapsed < 1.2  # ~one attempt (0.3 s), not 8 x 0.3 s


async def test_cached_keys_keep_working_while_the_breaker_is_open(
    key: SigningKey, other_key: SigningKey
) -> None:
    client = ScriptedClient(cooldown=60)
    client.behaviour = jwks_for(key)
    provider = JwksSigningKeyProvider(client)
    await provider.get_signing_key(mint_token(key))  # populates the cache (fetch #1)
    client.behaviour = _down()

    # An unknown kid forces a refresh attempt, which fails and opens the breaker...
    with pytest.raises(AuthKeysUnavailableError):
        await provider.get_signing_key(mint_token(other_key))
    assert client.fetches == 2
    # ...but a known kid is still answered from the cache,
    assert await provider.get_signing_key(mint_token(key)) is not None
    # and further unknown-kid probes fail fast without touching the network.
    with pytest.raises(AuthKeysUnavailableError):
        await provider.get_signing_key(mint_token(other_key))
    assert client.fetches == 2


async def test_worker_thread_use_is_bounded(key: SigningKey) -> None:
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    class _Slow:
        def get_signing_key_from_jwt(self, token: Any) -> Any:
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1

            class _Key:
                key = "k"

            return _Key()

    provider = JwksSigningKeyProvider(_Slow(), max_concurrent=3)

    results = await asyncio.gather(*(provider.get_signing_key("t") for _ in range(12)))

    assert results == ["k"] * 12
    assert state["peak"] <= 3


# -- the HTTP-level outcome ----------------------------------------------------------


def test_malformed_key_endpoint_is_503_over_http_while_a_bad_token_stays_401(
    anon_client: TestClient, key: SigningKey
) -> None:
    provider = _real_provider()
    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=["RS256"],
        leeway_seconds=30,
        key_provider=provider,
    )
    headers = {"Authorization": f"Bearer {mint_token(key)}"}

    with _key_endpoint_returns(b"<html>502 Bad Gateway</html>"):
        broken = anon_client.get("/api/v1/auth/me", headers=headers)
        garbage = anon_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})

    assert broken.status_code == 503
    assert broken.json()["error"]["code"] == "auth_unavailable"
    assert "Bad Gateway" not in broken.text and "html" not in broken.text.lower()
    assert garbage.status_code == 401  # a bad token is never reported as an outage
