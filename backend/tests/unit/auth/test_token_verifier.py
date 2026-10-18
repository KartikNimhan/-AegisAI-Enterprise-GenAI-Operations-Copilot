"""Token-verification contract: RS256 only (from config, not the token),
exact issuer, configured audience present, required claims exp/iat/iss/sub/aud,
`nbf` not required but enforced when present. Local throwaway keys only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization

from app.auth.exceptions import InvalidTokenError
from app.auth.tokens import MAX_TOKEN_CHARS, TokenVerifier

from ...auth_fixtures import (
    AUDIENCE,
    ISSUER,
    SigningKey,
    generate_signing_key,
    make_verifier,
    mint_token,
)


@pytest.fixture(scope="module")
def key() -> SigningKey:
    return generate_signing_key()


@pytest.fixture(scope="module")
def verifier(key: SigningKey) -> TokenVerifier:
    return make_verifier(key)


async def _reason(verifier: TokenVerifier, token: str) -> str:
    with pytest.raises(InvalidTokenError) as info:
        await verifier.verify(token)
    return info.value.reason


async def test_accepts_a_valid_token_with_an_audience_array_and_no_nbf(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    token = mint_token(key, drop=("nbf",))

    claims = await verifier.verify(token)

    assert claims.issuer == ISSUER
    assert claims.subject == "subject-1"
    assert claims.email == "user@example.test"
    assert claims.email_verified is True
    assert claims.token_id == "jti-1"


async def test_accepts_an_audience_given_as_a_single_string(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    await verifier.verify(mint_token(key, claims={"aud": AUDIENCE}))


@pytest.mark.parametrize("claim", ["exp", "iat", "iss", "sub", "aud"])
async def test_rejects_a_token_missing_a_required_claim(
    verifier: TokenVerifier, key: SigningKey, claim: str
) -> None:
    assert await _reason(verifier, mint_token(key, drop=(claim,))) == "missing_required_claim"


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"aud": ["account", "other-api"]}, "invalid_audience"),
        ({"aud": "other-api"}, "invalid_audience"),
        ({"iss": ISSUER + "/x"}, "invalid_issuer"),
        ({"iss": "https://evil.example.test/realms/aegis"}, "invalid_issuer"),
    ],
)
async def test_rejects_wrong_audience_or_issuer(
    verifier: TokenVerifier, key: SigningKey, claims: dict, reason: str
) -> None:
    assert await _reason(verifier, mint_token(key, claims=claims)) == reason


async def test_rejects_an_expired_token_but_allows_a_little_clock_skew(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    now = int(time.time())
    assert (
        await _reason(verifier, mint_token(key, claims={"iat": now - 4000, "exp": now - 3000}))
        == "expired"
    )
    await verifier.verify(mint_token(key, claims={"exp": now - 10}))  # within 30 s leeway


async def test_rejects_an_issued_at_or_not_before_in_the_future(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    now = int(time.time())
    far = now + 3600
    assert (
        await _reason(verifier, mint_token(key, claims={"iat": far, "exp": far + 900}))
        == "not_yet_valid"
    )
    # nbf is not required, but if present it is enforced.
    assert await _reason(verifier, mint_token(key, claims={"nbf": far})) == "not_yet_valid"


async def test_rejects_a_tampered_payload_with_the_original_signature(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    header, _payload, signature = mint_token(key).split(".")
    forged = base64.urlsafe_b64encode(
        json.dumps(
            {"iss": ISSUER, "sub": "attacker", "aud": [AUDIENCE], "iat": 1, "exp": 4102444800}
        ).encode()
    ).rstrip(b"=")

    assert await _reason(verifier, f"{header}.{forged.decode()}.{signature}") == "bad_signature"


async def test_rejects_alg_none(verifier: TokenVerifier, key: SigningKey) -> None:
    _header, payload, _sig = mint_token(key).split(".")
    none_header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT", "kid": key.kid}).encode()
    ).rstrip(b"=")

    assert await _reason(verifier, f"{none_header.decode()}.{payload}.") == "algorithm_not_allowed"


async def test_rejects_hs256_signed_with_the_public_key(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    """The classic algorithm-confusion attack: HMAC-sign with the (public) RSA key."""
    _header, payload, _sig = mint_token(key).split(".")
    public_pem = key.public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT", "kid": key.kid}).encode()
    ).rstrip(b"=")
    signing_input = f"{header.decode()}.{payload}".encode()
    signature = base64.urlsafe_b64encode(
        hmac.new(public_pem, signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")

    assert await _reason(verifier, f"{signing_input.decode()}.{signature.decode()}") == (
        "algorithm_not_allowed"
    )


async def test_rejects_an_algorithm_that_is_not_in_the_configured_allowlist(
    key: SigningKey,
) -> None:
    """RS384 is a legitimate RSA algorithm, but only RS256 is configured."""
    token = mint_token(key, algorithm="RS384")

    assert await _reason(make_verifier(key, algorithms=["RS256"]), token) == "algorithm_not_allowed"
    await make_verifier(key, algorithms=["RS256", "RS384"]).verify(token)


async def test_rejects_an_unknown_signing_key(verifier: TokenVerifier) -> None:
    other = generate_signing_key(kid="not-published")

    assert await _reason(verifier, mint_token(other)) == "unknown_signing_key"


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "not.a.jwt.at.all", "....", " "])
async def test_rejects_malformed_tokens(verifier: TokenVerifier, token: str) -> None:
    with pytest.raises(InvalidTokenError):
        await verifier.verify(token)


async def test_rejects_an_oversized_token_before_doing_any_work(verifier: TokenVerifier) -> None:
    assert await _reason(verifier, "a" * (MAX_TOKEN_CHARS + 1)) == "token_size"


async def test_rejects_a_non_string_subject(verifier: TokenVerifier, key: SigningKey) -> None:
    with pytest.raises(InvalidTokenError):
        await verifier.verify(mint_token(key, claims={"sub": 12345}))


@pytest.mark.parametrize("value", ["true", 1, None, "yes"])
async def test_email_verified_is_true_only_for_a_literal_boolean(
    verifier: TokenVerifier, key: SigningKey, value: object
) -> None:
    claims = await verifier.verify(mint_token(key, claims={"email_verified": value}))

    assert claims.email_verified is False


async def test_a_missing_email_is_not_an_error_for_verification(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    claims = await verifier.verify(mint_token(key, drop=("email", "email_verified", "jti")))

    assert claims.email is None
    assert claims.email_verified is False
    assert claims.token_id is None
