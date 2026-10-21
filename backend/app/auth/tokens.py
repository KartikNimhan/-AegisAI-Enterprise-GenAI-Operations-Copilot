"""Access-token verification.

Contract (verified against a real Keycloak token in the M12 Phase 0 spike):
- signature algorithm from a configured asymmetric allowlist — never taken
  from the token header, and checked against the header before any key lookup;
- issuer must equal the configured issuer exactly;
- audience: the configured API audience must be present (an `aud` array that
  contains it is fine; `strict_aud` is deliberately not used);
- required claims: exp, iat, iss, sub, aud. `nbf` is NOT required (Keycloak
  omits it) but is enforced if present;
- small configurable clock leeway.
Failures raise `InvalidTokenError` with a short reason for server-side
logging only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt

from app.auth.exceptions import InvalidTokenError
from app.auth.jwks import JwksSigningKeyProvider, SigningKeyProvider
from app.config import Settings

MAX_TOKEN_CHARS = 8192
REQUIRED_CLAIMS = ["exp", "iat", "iss", "sub", "aud"]
_MAX_SUBJECT_CHARS = 255

_REASON_BY_EXCEPTION: tuple[tuple[type[Exception], str], ...] = (
    (jwt.ExpiredSignatureError, "expired"),
    (jwt.InvalidAudienceError, "invalid_audience"),
    (jwt.InvalidIssuerError, "invalid_issuer"),
    (jwt.MissingRequiredClaimError, "missing_required_claim"),
    (jwt.ImmatureSignatureError, "not_yet_valid"),
    (jwt.InvalidSignatureError, "bad_signature"),
    (jwt.InvalidAlgorithmError, "algorithm_not_allowed"),
)


@dataclass(frozen=True)
class VerifiedClaims:
    issuer: str
    subject: str
    email: str | None
    email_verified: bool
    token_id: str | None
    expires_at: int


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: list[str],
        leeway_seconds: int,
        key_provider: SigningKeyProvider,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._algorithms = list(algorithms)
        self._leeway = leeway_seconds
        self._keys = key_provider

    @classmethod
    def from_settings(
        cls, settings: Settings, key_provider: SigningKeyProvider | None = None
    ) -> TokenVerifier:
        assert settings.auth_issuer and settings.auth_audience
        return cls(
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            algorithms=settings.auth_allowed_algorithms,
            leeway_seconds=settings.auth_leeway_seconds,
            key_provider=key_provider or JwksSigningKeyProvider.from_settings(settings),
        )

    async def verify(self, token: str) -> VerifiedClaims:
        if not token or len(token) > MAX_TOKEN_CHARS:
            raise InvalidTokenError("token_size")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed_token") from exc
        if header.get("alg") not in self._algorithms:
            # Rejects "none", HMAC, and anything off-allowlist before touching keys.
            raise InvalidTokenError("algorithm_not_allowed")

        key = await self._keys.get_signing_key(token)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            reason = next(
                (r for t, r in _REASON_BY_EXCEPTION if isinstance(exc, t)), "invalid_token"
            )
            raise InvalidTokenError(reason) from exc
        except (TypeError, ValueError) as exc:
            # PyJWT raises a plain TypeError (not a PyJWTError) when the key it is
            # given cannot verify the token's algorithm, e.g. an RS256 token whose
            # `kid` names an EC key in the key set, or the reverse. The caller
            # chooses both `alg` and `kid`, so this is a rejected token, not a
            # server error. Deliberately limited to these two types and to this
            # call: anything else still surfaces as the bug it would be.
            raise InvalidTokenError("key_algorithm_mismatch") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > _MAX_SUBJECT_CHARS:
            raise InvalidTokenError("invalid_subject")
        email = claims.get("email")
        jti = claims.get("jti")
        return VerifiedClaims(
            issuer=str(claims["iss"]),
            subject=subject,
            email=email if isinstance(email, str) else None,
            # Only a literal boolean true counts as verified.
            email_verified=claims.get("email_verified") is True,
            token_id=jti if isinstance(jti, str) else None,
            expires_at=int(claims["exp"]),
        )
