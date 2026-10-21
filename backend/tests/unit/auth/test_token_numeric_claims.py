"""Correctly signed tokens whose numeric claims are non-finite or the wrong type.

Signature verification happens before claim validation, so only a token the
identity provider itself signed can reach this code, but a misbehaving provider
(or a library that raised something other than `PyJWTError` for an odd number)
must still produce a clean 401-style rejection, never an unhandled exception
that would surface as a 500. The payloads are signed by hand because PyJWT's
own encoder refuses to produce most of them. Local throwaway keys only.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from app.auth.exceptions import InvalidTokenError
from app.auth.tokens import TokenVerifier

from ...auth_fixtures import AUDIENCE, ISSUER, SigningKey, generate_signing_key, make_verifier


@pytest.fixture(scope="module")
def key() -> SigningKey:
    return generate_signing_key()


@pytest.fixture(scope="module")
def verifier(key: SigningKey) -> TokenVerifier:
    return make_verifier(key)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _sign_payload_text(key: SigningKey, payload_json: str) -> str:
    header = _b64(json.dumps({"alg": "RS256", "kid": key.kid}).encode())
    body = _b64(payload_json.encode())
    signature = key.private_key.sign(
        f"{header}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    return f"{header}.{body}.{_b64(signature)}"


def _payload(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "subject-1",
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 900,
    }
    return {**base, **overrides}


# json.dumps writes float("inf") / float("nan") as the bare tokens Infinity / NaN,
# which Python's JSON parser accepts (strict JSON parsers do not).
NON_FINITE_OR_WRONG_TYPE: dict[str, dict[str, Any]] = {
    "exp is Infinity": _payload(exp=float("inf")),
    "exp is -Infinity": _payload(exp=float("-inf")),
    "exp is NaN": _payload(exp=float("nan")),
    "iat is Infinity": _payload(iat=float("inf")),
    "nbf is Infinity": _payload(nbf=float("inf")),
    "exp is a string": _payload(exp="soon"),
    "iat is a string": _payload(iat="now"),
    "nbf is a string": _payload(nbf="later"),
    "jti is a number": _payload(jti=5),
}


@pytest.mark.parametrize("name", list(NON_FINITE_OR_WRONG_TYPE))
async def test_odd_numeric_claims_are_a_clean_rejection(
    verifier: TokenVerifier, key: SigningKey, name: str
) -> None:
    token = _sign_payload_text(key, json.dumps(NON_FINITE_OR_WRONG_TYPE[name]))

    with pytest.raises(InvalidTokenError) as info:
        await verifier.verify(token)

    assert info.value.reason  # a short reason for the server-side log


async def test_a_numeric_literal_too_large_for_a_float_is_a_clean_rejection(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    text = json.dumps(_payload(exp=1)).replace('"exp": 1', '"exp": 1e999')
    assert "1e999" in text  # the replacement really happened

    with pytest.raises(InvalidTokenError):
        await verifier.verify(_sign_payload_text(key, text))


@pytest.mark.parametrize("payload_text", ["[1, 2]", '"a string"', "42", "null", "not json"])
async def test_a_signed_payload_that_is_not_a_json_object_is_a_clean_rejection(
    verifier: TokenVerifier, key: SigningKey, payload_text: str
) -> None:
    with pytest.raises(InvalidTokenError):
        await verifier.verify(_sign_payload_text(key, payload_text))


async def test_a_non_string_email_is_ignored_rather_than_trusted(
    verifier: TokenVerifier, key: SigningKey
) -> None:
    token = _sign_payload_text(key, json.dumps(_payload(email={"a": 1}, email_verified="true")))

    claims = await verifier.verify(token)

    assert claims.email is None
    assert claims.email_verified is False  # only a literal boolean true counts
