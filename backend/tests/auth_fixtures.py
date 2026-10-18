"""Helpers for authentication tests: throwaway RSA keys, token minting, and
in-memory stand-ins for the key set and the identity tables. No real tokens,
no network, no database."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.auth.exceptions import InvalidTokenError
from app.auth.tokens import TokenVerifier
from app.db.repositories.identity_repository import IdentityContext
from app.domain.enums.user_role import UserRole
from app.domain.models.organization import Organization
from app.domain.models.user import User

ISSUER = "https://idp.example.test/realms/aegis"
AUDIENCE = "aegisai-api"
JWKS_URL = "https://idp.example.test/realms/aegis/protocol/openid-connect/certs"
DEFAULT_KID = "sig-1"


@dataclass
class SigningKey:
    private_key: rsa.RSAPrivateKey
    kid: str = DEFAULT_KID

    @property
    def public_key(self) -> Any:
        return self.private_key.public_key()


def generate_signing_key(kid: str = DEFAULT_KID) -> SigningKey:
    return SigningKey(
        private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048), kid=kid
    )


def jwks_for(*keys: SigningKey, include_encryption_key: bool = True) -> dict[str, Any]:
    """A JWK Set shaped like Keycloak's: signing keys plus an encryption-only key."""
    entries: list[dict[str, Any]] = []
    for key in keys:
        jwk = RSAAlgorithm.to_jwk(key.public_key, as_dict=True)
        entries.append({**jwk, "kid": key.kid, "alg": "RS256", "use": "sig"})
    if include_encryption_key and keys:
        jwk = RSAAlgorithm.to_jwk(keys[0].public_key, as_dict=True)
        entries.append({**jwk, "kid": "enc-1", "alg": "RSA-OAEP", "use": "enc"})
    return {"keys": entries}


def mint_token(
    key: SigningKey,
    *,
    claims: dict[str, Any] | None = None,
    drop: tuple[str, ...] = (),
    headers: dict[str, Any] | None = None,
    algorithm: str = "RS256",
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "subject-1",
        "aud": [AUDIENCE, "account"],
        "iat": now,
        "exp": now + 900,
        "email": "user@example.test",
        "email_verified": True,
        "jti": "jti-1",
    }
    payload.update(claims or {})
    for name in drop:
        payload.pop(name, None)
    return jwt.encode(
        payload, key.private_key, algorithm=algorithm, headers={"kid": key.kid, **(headers or {})}
    )


class StaticKeyProvider:
    """A `SigningKeyProvider` over in-memory keys (the real one wraps PyJWKClient)."""

    def __init__(self, *keys: SigningKey) -> None:
        self._keys = {k.kid: k for k in keys}

    async def get_signing_key(self, token: str) -> Any:
        kid = jwt.get_unverified_header(token).get("kid")
        key = self._keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise InvalidTokenError("unknown_signing_key")
        return key.public_key


def make_verifier(
    *keys: SigningKey, algorithms: list[str] | None = None, leeway: int = 30
) -> TokenVerifier:
    return TokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        algorithms=algorithms or ["RS256"],
        leeway_seconds=leeway,
        key_provider=StaticKeyProvider(*keys),
    )


class FakeIdentityRepository:
    """In-memory stand-in for `IdentityRepository` (counts lookups so tests can
    prove identity was checked on each hop)."""

    def __init__(self) -> None:
        self._contexts: dict[tuple[str, str], IdentityContext] = {}
        self.lookups = 0
        self.fail_with: Exception | None = None

    def link(
        self,
        *,
        subject: str = "subject-1",
        issuer: str = ISSUER,
        email: str = "db-user@example.test",
        role: UserRole = UserRole.MEMBER,
        user_active: bool = True,
        organization_active: bool = True,
    ) -> IdentityContext:
        organization = Organization(
            id=uuid.uuid4(), name=f"org-{uuid.uuid4()}", is_active=organization_active
        )
        user = User(
            id=uuid.uuid4(),
            organization_id=organization.id,
            email=email,
            role=role,
            is_active=user_active,
        )
        context = IdentityContext(user=user, organization=organization)
        self._contexts[(issuer, subject)] = context
        return context

    async def get_context(self, *, issuer: str, subject: str) -> IdentityContext | None:
        self.lookups += 1
        if self.fail_with is not None:
            raise self.fail_with
        return self._contexts.get((issuer, subject))
