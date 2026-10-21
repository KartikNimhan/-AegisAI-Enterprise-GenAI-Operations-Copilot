"""Regression for security review finding F1: a signing key that cannot verify the
token's algorithm used to escape `TokenVerifier.verify` as a plain `TypeError`
(PyJWT raises it from `prepare_key`, and it is not a `PyJWTError`), which the
application turned into a generic HTTP 500 and a logged traceback for what is an
unauthenticated, attacker-chosen input (`alg` and `kid` are both caller-supplied).
It must be an ordinary rejected token: HTTP 401, same generic response.

The key lookup is stubbed so the key set can contain key types the RSA-only test
fixtures never produce. Throwaway local keys only; no network, no database.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

from app.auth.exceptions import InvalidTokenError
from app.auth.tokens import TokenVerifier
from app.core.security import get_token_verifier
from app.main import app

from ...auth_fixtures import AUDIENCE, ISSUER

ME = "/api/v1/auth/me"
KID = "sig-1"


class _FixedKeyProvider:
    """Returns whatever key object it is given, for any token (the real provider
    hands back the key whose `kid` matches the token's header)."""

    def __init__(self, key: Any) -> None:
        self._key = key

    async def get_signing_key(self, token: str) -> Any:
        return self._key


def _verifier(key: Any, algorithms: list[str]) -> TokenVerifier:
    return TokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=algorithms,
        leeway_seconds=30,
        key_provider=_FixedKeyProvider(key),
    )


def _mint(private_key: Any, algorithm: str) -> str:
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "sub": "subject-1",
        "aud": [AUDIENCE],
        "iat": now,
        "exp": now + 900,
    }
    return jwt.encode(payload, private_key, algorithm=algorithm, headers={"kid": KID})


@pytest.fixture(scope="module")
def rsa_private() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_private() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


# -- the verifier itself ------------------------------------------------------------


async def test_an_rs256_token_whose_kid_names_an_ec_key_is_rejected_not_a_server_error(
    rsa_private: rsa.RSAPrivateKey, ec_private: ec.EllipticCurvePrivateKey
) -> None:
    token = _mint(rsa_private, "RS256")

    with pytest.raises(InvalidTokenError) as info:
        await _verifier(ec_private.public_key(), ["RS256"]).verify(token)

    assert info.value.reason == "key_algorithm_mismatch"
    assert isinstance(info.value.__cause__, TypeError)  # the confirmed PyJWT behavior


async def test_an_es256_token_against_an_rsa_key_is_rejected_when_both_algorithms_are_allowed(
    rsa_private: rsa.RSAPrivateKey, ec_private: ec.EllipticCurvePrivateKey
) -> None:
    token = _mint(ec_private, "ES256")

    with pytest.raises(InvalidTokenError) as info:
        await _verifier(rsa_private.public_key(), ["RS256", "ES256"]).verify(token)

    assert info.value.reason == "key_algorithm_mismatch"


async def test_a_forged_token_with_a_published_ec_kid_is_rejected(
    ec_private: ec.EllipticCurvePrivateKey,
) -> None:
    """The exact unauthenticated input from the review: an RS256 header naming an
    EC key's kid, an arbitrary payload and a junk signature."""

    def segment(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    forged = f"{segment({'alg': 'RS256', 'kid': KID})}.{segment({'sub': 'x'})}.c2ln"

    with pytest.raises(InvalidTokenError) as info:
        await _verifier(ec_private.public_key(), ["RS256"]).verify(forged)

    assert info.value.reason == "key_algorithm_mismatch"


@pytest.mark.parametrize("unusable", [None, object(), 12345, [b"not a key"]])
async def test_a_key_object_pyjwt_cannot_use_is_a_rejected_token(
    rsa_private: rsa.RSAPrivateKey, unusable: Any
) -> None:
    """PyJWT cannot tell 'wrong type of key' from 'not a key at all' (both are the
    same TypeError), so both take the same controlled path."""
    with pytest.raises(InvalidTokenError) as info:
        await _verifier(unusable, ["RS256"]).verify(_mint(rsa_private, "RS256"))

    assert info.value.reason == "key_algorithm_mismatch"


async def test_matching_key_types_still_verify_so_the_guard_is_not_rejecting_everything(
    rsa_private: rsa.RSAPrivateKey, ec_private: ec.EllipticCurvePrivateKey
) -> None:
    both = ["RS256", "ES256"]

    rsa_claims = await _verifier(rsa_private.public_key(), both).verify(_mint(rsa_private, "RS256"))
    ec_claims = await _verifier(ec_private.public_key(), both).verify(_mint(ec_private, "ES256"))

    assert rsa_claims.subject == ec_claims.subject == "subject-1"


async def test_ordinary_rejections_keep_their_specific_reasons(
    rsa_private: rsa.RSAPrivateKey,
) -> None:
    """The new clause sits after the PyJWTError clause, so it cannot shadow it."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(InvalidTokenError) as info:
        await _verifier(rsa_private.public_key(), ["RS256"]).verify(_mint(other, "RS256"))

    assert info.value.reason == "bad_signature"


# -- through the real application ----------------------------------------------------


@pytest.mark.parametrize(
    ("key_kind", "algorithm", "allowed"),
    [
        ("ec", "RS256", ["RS256"]),
        ("rsa", "ES256", ["RS256", "ES256"]),
        ("none", "RS256", ["RS256"]),
    ],
)
def test_the_http_response_is_the_generic_401_never_a_500(
    auth_env: None,
    rsa_private: rsa.RSAPrivateKey,
    ec_private: ec.EllipticCurvePrivateKey,
    key_kind: str,
    algorithm: str,
    allowed: list[str],
) -> None:
    published: Any = {
        "ec": ec_private.public_key(),
        "rsa": rsa_private.public_key(),
        "none": None,
    }[key_kind]
    signer = ec_private if algorithm == "ES256" else rsa_private
    app.dependency_overrides[get_token_verifier] = lambda: _verifier(published, allowed)

    # raise_server_exceptions=False so a regression shows up as a 500 status, not
    # as an exception thrown into the test.
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(ME, headers={"Authorization": f"Bearer {_mint(signer, algorithm)}"})

    assert response.status_code == 401
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("unauthorized", "Authentication required")
    assert response.headers["www-authenticate"] == "Bearer"
    assert "internal_error" not in response.text
