"""The real PyJWT key client (cache, `kid` matching, rate-limited refresh), as
wrapped by our `GuardedJWKClient`, driven through `JwksSigningKeyProvider`, with
only the HTTP fetch faked."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest

from app.auth.exceptions import AuthKeysUnavailableError, InvalidTokenError
from app.auth.jwks import GuardedJWKClient, JwksSigningKeyProvider

from ...auth_fixtures import JWKS_URL, SigningKey, generate_signing_key, jwks_for, mint_token


class _FakeFetchClient(GuardedJWKClient):
    """The guarded client (what production builds) with the network fetch
    replaced; everything else (caching, kid lookup, refresh cooldown) is the real
    implementation."""

    def __init__(self, jwk_set: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(JWKS_URL, failure_cooldown_seconds=0, **kwargs)
        self.jwk_set = jwk_set
        self.fetches = 0
        self.fail = False

    def fetch_data(self) -> Any:
        self.fetches += 1
        if self.fail:
            raise jwt.PyJWKClientConnectionError("simulated outage")
        self._last_successful_fetch = time.monotonic()
        return self.jwk_set


@pytest.fixture(scope="module")
def key_a() -> SigningKey:
    return generate_signing_key("key-a")


@pytest.fixture(scope="module")
def key_b() -> SigningKey:
    return generate_signing_key("key-b")


async def test_a_known_key_is_fetched_once_and_then_served_from_cache(key_a: SigningKey) -> None:
    client = _FakeFetchClient(jwks_for(key_a), cache_jwk_set=True, lifespan=600)
    provider = JwksSigningKeyProvider(client)

    for _ in range(3):
        assert await provider.get_signing_key(mint_token(key_a)) is not None

    assert client.fetches == 1


async def test_an_encryption_only_key_is_never_returned_as_a_signing_key(key_a: SigningKey) -> None:
    client = _FakeFetchClient(jwks_for(key_a, include_encryption_key=True))
    provider = JwksSigningKeyProvider(client)
    token = mint_token(key_a, headers={"kid": "enc-1"})

    with pytest.raises(InvalidTokenError) as info:
        await provider.get_signing_key(token)

    assert info.value.reason == "unknown_signing_key"


async def test_a_rotated_key_is_picked_up_by_one_refresh(
    key_a: SigningKey, key_b: SigningKey
) -> None:
    client = _FakeFetchClient(
        jwks_for(key_a), cache_jwk_set=True, lifespan=600, cooldown_duration=0
    )
    provider = JwksSigningKeyProvider(client)
    await provider.get_signing_key(mint_token(key_a))  # fetch #1
    client.jwk_set = jwks_for(key_a, key_b)  # the provider rotates keys

    assert await provider.get_signing_key(mint_token(key_b)) is not None

    assert client.fetches == 2


async def test_an_unknown_kid_triggers_at_most_one_refresh_then_is_rejected(
    key_a: SigningKey, key_b: SigningKey
) -> None:
    client = _FakeFetchClient(
        jwks_for(key_a), cache_jwk_set=True, lifespan=600, cooldown_duration=0
    )
    provider = JwksSigningKeyProvider(client)
    await provider.get_signing_key(mint_token(key_a))  # fetch #1

    with pytest.raises(InvalidTokenError) as info:
        await provider.get_signing_key(mint_token(key_b))

    assert info.value.reason == "unknown_signing_key"
    assert client.fetches == 2  # exactly one refresh for the unknown kid


async def test_refreshes_for_unknown_kids_are_rate_limited_by_the_cooldown(
    key_a: SigningKey, key_b: SigningKey
) -> None:
    client = _FakeFetchClient(
        jwks_for(key_a), cache_jwk_set=True, lifespan=600, cooldown_duration=300
    )
    provider = JwksSigningKeyProvider(client)
    await provider.get_signing_key(mint_token(key_a))  # fetch #1 (starts the cooldown)

    for _ in range(5):  # an attacker spraying tokens with unknown kids
        with pytest.raises(InvalidTokenError):
            await provider.get_signing_key(mint_token(key_b))

    assert client.fetches == 1  # no extra fetches inside the cooldown


async def test_an_outage_with_nothing_cached_fails_closed(key_a: SigningKey) -> None:
    client = _FakeFetchClient(jwks_for(key_a))
    client.fail = True
    provider = JwksSigningKeyProvider(client)

    with pytest.raises(AuthKeysUnavailableError):
        await provider.get_signing_key(mint_token(key_a))


async def test_an_outage_while_the_cache_is_still_valid_keeps_working(key_a: SigningKey) -> None:
    client = _FakeFetchClient(jwks_for(key_a), cache_jwk_set=True, lifespan=600)
    provider = JwksSigningKeyProvider(client)
    await provider.get_signing_key(mint_token(key_a))
    client.fail = True

    assert await provider.get_signing_key(mint_token(key_a)) is not None


async def test_a_token_that_is_not_a_jwt_is_an_invalid_token(key_a: SigningKey) -> None:
    provider = JwksSigningKeyProvider(_FakeFetchClient(jwks_for(key_a)))

    with pytest.raises(InvalidTokenError):
        await provider.get_signing_key("not-a-jwt")


def test_the_real_client_refuses_non_http_key_set_urls() -> None:
    with pytest.raises(jwt.PyJWKClientError):
        jwt.PyJWKClient("file:///etc/passwd")
