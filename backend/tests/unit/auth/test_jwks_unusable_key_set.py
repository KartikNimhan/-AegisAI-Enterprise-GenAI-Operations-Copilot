"""Regressions for security review findings F2 and F3.

F2: a key-set response that parses but holds no usable signing key (only `use:
enc` keys, or keys without a `kid`) was cached by PyJWT before being checked, and
every later lookup then failed from that cache, with no refetch, until the full
cache lifetime (600 s by default) expired. It must instead cost one cooldown
window.

F3: "unknown kid" used to be recognised by searching PyJWT's exception message for
a phrase. It is now decided from the data (a usable key set that lacks the `kid`),
so these tests also run with PyJWT's wording replaced.

The real PyJWT client and our `GuardedJWKClient` run end to end; only the HTTP
layer underneath is faked. Throwaway keys, no network, no database.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.exceptions import AuthKeysUnavailableError, InvalidTokenError
from app.auth.jwks import JwksSigningKeyProvider
from app.auth.tokens import TokenVerifier
from app.core.security import get_token_verifier
from app.main import app

from ...auth_fixtures import (
    AUDIENCE,
    ISSUER,
    FakeIdentityRepository,
    SigningKey,
    generate_signing_key,
    jwks_for,
    mint_token,
)

COOLDOWN = 0.3  # seconds the breaker stays open after an unusable response


@pytest.fixture(scope="module")
def key_a() -> SigningKey:
    return generate_signing_key("key-a")


@pytest.fixture(scope="module")
def key_b() -> SigningKey:
    return generate_signing_key("key-b")


def _body(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj).encode()


def _enc_only(key: SigningKey) -> bytes:
    """Parses fine (a supported algorithm), but its only key is for encryption, so
    there is no signing key. This is the F2 case: PyJWT caches such a set."""
    return _body({"keys": [{**jwks_for(key)["keys"][0], "use": "enc"}]})


def _enc_only_unsupported_alg(key: SigningKey) -> bytes:
    """Keycloak's real encryption key (`RSA-OAEP`), which PyJWT cannot construct:
    the set is rejected while parsing and was never cached. A control case."""
    encryption_key = jwks_for(key)["keys"][-1]
    assert (encryption_key["use"], encryption_key["alg"]) == ("enc", "RSA-OAEP")
    return _body({"keys": [encryption_key]})


def _without_kid(key: SigningKey) -> bytes:
    """Parses fine, but its only key has no `kid`, so PyJWT cannot offer it."""
    signing = {k: v for k, v in jwks_for(key)["keys"][0].items() if k != "kid"}
    return _body({"keys": [signing]})


@contextmanager
def _serving(*bodies: bytes) -> Iterator[list[int]]:
    """Fakes only the HTTP layer under PyJWT's real fetch/parse/cache code. The
    n-th fetch returns `bodies[n]` (the last body repeats). Yields a list with
    one entry per network fetch, so `len(opens)` is the number of fetches."""
    original = urllib.request.build_opener
    opens: list[int] = []

    class _Opener:
        def open(self, request: Any, timeout: Any = None) -> Any:
            body = bodies[min(len(opens), len(bodies) - 1)]
            opens.append(1)

            @contextmanager
            def response() -> Iterator[io.BytesIO]:
                yield io.BytesIO(body)

            return response()

    urllib.request.build_opener = lambda *a, **k: _Opener()  # type: ignore[assignment]
    try:
        yield opens
    finally:
        urllib.request.build_opener = original


def _provider(*, cooldown: float = COOLDOWN, cache_seconds: int = 600) -> JwksSigningKeyProvider:
    return JwksSigningKeyProvider.create(
        jwks_url="https://idp.example.test/certs",
        cache_seconds=cache_seconds,
        timeout=5,
        min_refresh_seconds=0,
        failure_cooldown_seconds=cooldown,
    )


def _kidless_token() -> str:
    def segment(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{segment({'alg': 'RS256'})}.{segment({'sub': 'x'})}.c2ln"


# -- F2: an unusable key set must not outlive one cooldown window ---------------------


@pytest.mark.parametrize(
    "unusable",
    [_enc_only, _without_kid, _enc_only_unsupported_alg],
    ids=["enc-only", "no-kid", "unparsable-enc-key"],
)
async def test_an_unusable_key_set_is_a_503_that_recovers_after_one_cooldown(
    key_a: SigningKey, unusable: Any
) -> None:
    provider = _provider()  # the cache would otherwise keep the bad set for 600 s
    token = mint_token(key_a)

    with _serving(unusable(key_a), _body(jwks_for(key_a))) as opens:
        with pytest.raises(AuthKeysUnavailableError):  # fetch #1: unusable
            await provider.get_signing_key(token)
        with pytest.raises(AuthKeysUnavailableError):  # inside the cooldown
            await provider.get_signing_key(token)
        assert len(opens) == 1  # ...and it cost no second fetch

        await asyncio.sleep(COOLDOWN + 0.15)

        assert await provider.get_signing_key(token) is not None  # fetch #2: recovered
        assert await provider.get_signing_key(token) is not None  # now served from cache
        assert len(opens) == 2


async def test_an_unusable_key_set_is_never_reported_as_the_callers_fault(
    key_a: SigningKey,
) -> None:
    """An unusable key set is infrastructure trouble (503, reported with the
    infrastructure reason), never the 401 reserved for 'the key set is fine, your
    kid is not in it'. Before the fix it was reported as `jwks_unusable`."""
    provider = _provider()

    with _serving(_enc_only(key_a)), pytest.raises(AuthKeysUnavailableError) as info:
        await provider.get_signing_key(mint_token(key_a))

    assert info.value.reason == "jwks_unreachable"


async def test_a_refresh_that_returns_an_unusable_set_drops_it_and_recovers(
    key_a: SigningKey, key_b: SigningKey
) -> None:
    """Rotation going wrong: the unknown-kid refresh gets a set with no signing
    keys. That is an outage (503), not a bad token, and the previously cached keys
    are not kept alongside it; once the identity provider serves a good set both
    keys work again after one cooldown."""
    provider = _provider()

    with _serving(_body(jwks_for(key_a)), _enc_only(key_a), _body(jwks_for(key_a, key_b))) as opens:
        assert await provider.get_signing_key(mint_token(key_a)) is not None  # fetch #1
        with pytest.raises(AuthKeysUnavailableError):  # unknown kid -> refresh #2: unusable
            await provider.get_signing_key(mint_token(key_b))
        with pytest.raises(AuthKeysUnavailableError):  # known kid, but the cache was dropped
            await provider.get_signing_key(mint_token(key_a))
        assert len(opens) == 2  # no network inside the cooldown

        await asyncio.sleep(COOLDOWN + 0.15)

        assert await provider.get_signing_key(mint_token(key_b)) is not None  # fetch #3
        assert await provider.get_signing_key(mint_token(key_a)) is not None
        assert len(opens) == 3


async def test_a_refresh_that_returns_an_unparsable_set_keeps_the_good_cached_keys(
    key_a: SigningKey, key_b: SigningKey
) -> None:
    """Existing behavior that must not regress: a response PyJWT cannot even parse
    is never cached, so keys already cached keep working through it."""
    provider = _provider()

    with _serving(_body(jwks_for(key_a)), _enc_only_unsupported_alg(key_a)) as opens:
        assert await provider.get_signing_key(mint_token(key_a)) is not None  # fetch #1
        with pytest.raises(AuthKeysUnavailableError):  # unknown kid -> refresh #2: unparsable
            await provider.get_signing_key(mint_token(key_b))
        assert await provider.get_signing_key(mint_token(key_a)) is not None  # still cached
        assert len(opens) == 2


# -- F3: unknown kid, decided without exception-message text -------------------------


async def test_an_unknown_kid_is_a_401_class_error_and_leaves_the_cache_intact(
    key_a: SigningKey, key_b: SigningKey
) -> None:
    provider = _provider()

    with _serving(_body(jwks_for(key_a))) as opens:
        assert await provider.get_signing_key(mint_token(key_a)) is not None
        with pytest.raises(InvalidTokenError) as info:
            await provider.get_signing_key(mint_token(key_b))
        assert info.value.reason == "unknown_signing_key"
        assert len(opens) == 2  # one refresh for the unknown kid, no more

        # An unknown kid must not open the breaker or drop the good keys.
        assert await provider.get_signing_key(mint_token(key_a)) is not None
        assert len(opens) == 2


async def test_a_token_without_a_kid_is_an_unknown_key_not_a_server_error(
    key_a: SigningKey,
) -> None:
    provider = _provider()

    with _serving(_body(jwks_for(key_a))), pytest.raises(InvalidTokenError) as info:
        await provider.get_signing_key(_kidless_token())

    assert info.value.reason == "unknown_signing_key"


@pytest.fixture
def reworded_pyjwt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaces the text of PyJWT's 'no matching key' error, as a future release
    might. Classification must not care."""
    original = jwt.PyJWKClient.get_signing_key

    def reworded(self: jwt.PyJWKClient, kid: str) -> jwt.PyJWK:
        try:
            return original(self, kid)
        except jwt.PyJWKClientConnectionError:
            raise
        except jwt.PyJWKClientError as exc:
            raise jwt.PyJWKClientError("lookup failed (entirely different wording)") from exc

    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key", reworded)


async def test_unknown_kid_classification_does_not_depend_on_pyjwt_wording(
    reworded_pyjwt: None, key_a: SigningKey, key_b: SigningKey
) -> None:
    provider = _provider()

    with _serving(_body(jwks_for(key_a))):
        assert await provider.get_signing_key(mint_token(key_a)) is not None
        with pytest.raises(InvalidTokenError) as info:
            await provider.get_signing_key(mint_token(key_b))

    assert info.value.reason == "unknown_signing_key"


async def test_unusable_key_set_classification_does_not_depend_on_pyjwt_wording(
    reworded_pyjwt: None, key_a: SigningKey
) -> None:
    provider = _provider()

    with _serving(_enc_only(key_a)), pytest.raises(AuthKeysUnavailableError):
        await provider.get_signing_key(mint_token(key_a))


async def test_an_unexplained_client_error_for_a_published_kid_is_a_503_not_a_401(
    monkeypatch: pytest.MonkeyPatch, key_a: SigningKey
) -> None:
    """If PyJWT fails although the key IS in a usable set, that is not an unknown
    kid; the caller must not be told their token is bad."""

    def failing(self: jwt.PyJWKClient, kid: str) -> jwt.PyJWK:
        raise jwt.PyJWKClientError("something else went wrong")

    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key", failing)
    provider = _provider()

    with _serving(_body(jwks_for(key_a))), pytest.raises(AuthKeysUnavailableError) as info:
        await provider.get_signing_key(mint_token(key_a))

    assert info.value.reason == "jwks_unusable"


# -- through the real application ----------------------------------------------------


def test_http_unusable_key_set_is_503_then_recovers_while_an_unknown_kid_stays_401(
    auth_env: None, identity_repo: FakeIdentityRepository, key_a: SigningKey, key_b: SigningKey
) -> None:
    identity_repo.link()
    provider = _provider()
    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=["RS256"],
        leeway_seconds=30,
        key_provider=provider,
    )
    me = "/api/v1/auth/me"

    with (
        TestClient(app, raise_server_exceptions=False) as client,
        _serving(_enc_only(key_a), _body(jwks_for(key_a))) as opens,
    ):
        headers = {"Authorization": f"Bearer {mint_token(key_a)}"}
        unusable = client.get(me, headers=headers)
        assert unusable.status_code == 503
        assert unusable.json()["error"]["code"] == "auth_unavailable"
        assert "enc" not in unusable.text and "key" not in unusable.text.lower()

        time.sleep(COOLDOWN + 0.15)

        assert client.get(me, headers=headers).status_code == 200  # recovered
        assert len(opens) == 2

        unknown = client.get(
            me, headers={"Authorization": f"Bearer {mint_token(key_b)}"}
        )  # healthy set, kid not in it
        assert unknown.status_code == 401
        assert unknown.json()["error"]["code"] == "unauthorized"
