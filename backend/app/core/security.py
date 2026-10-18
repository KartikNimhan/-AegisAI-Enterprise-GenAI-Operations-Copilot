"""FastAPI authentication dependencies (Milestone 12, Phase 1a).

`get_current_principal` is attached ONCE, at router-inclusion level
(`app.api.router`), so a newly added route is protected by default; the only
unauthenticated routes are the explicit public ones listed in
`app.api.router` / `app.main` (health probes, the well-known agent card and
the three agent cards). There is deliberately no "authentication off" switch:
tests override the dependencies instead.

Failure responses are generic and consistent (see `app.core.exceptions`):
  401  missing/invalid/expired token (any token problem)
  403  valid token, but unknown identity or a disabled user/organization
  503  authentication not configured, key set unreachable, or database error
The specific reason is logged server-side (with the request id) and never
includes the token.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

import structlog
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from app.auth.exceptions import (
    AccountDisabledError,
    AuthError,
    AuthKeysUnavailableError,
    IdentityNotLinkedError,
)
from app.auth.jwks import JwksSigningKeyProvider
from app.auth.principal import Principal
from app.auth.service import IdentityService
from app.auth.tokens import TokenVerifier
from app.core.exceptions import AuthUnavailableError, ForbiddenError, UnauthorizedError
from app.db.repositories.identity_repository import IdentityRepository
from app.dependencies import DBSessionDep, SettingsDep

__all__ = [
    "AdminDep",
    "BearerTokenDep",
    "Principal",
    "PrincipalDep",
    "get_bearer_token",
    "get_current_principal",
    "get_identity_service",
    "get_token_verifier",
    "require_admin",
]

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False, description="OIDC access token (JWT)")
_BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]


@lru_cache(maxsize=4)
def _cached_verifier(
    issuer: str,
    audience: str,
    jwks_url: str,
    algorithms: tuple[str, ...],
    leeway: int,
    cache_seconds: int,
    min_refresh: float,
    timeout: float,
) -> TokenVerifier:
    # Keyed on primitives (Settings is unhashable) so one verifier — hence one
    # cached key set — is shared across requests.
    return TokenVerifier(
        issuer=issuer,
        audience=audience,
        algorithms=list(algorithms),
        leeway_seconds=leeway,
        key_provider=JwksSigningKeyProvider.create(
            jwks_url=jwks_url,
            cache_seconds=cache_seconds,
            timeout=timeout,
            min_refresh_seconds=min_refresh,
        ),
    )


def get_token_verifier(settings: SettingsDep) -> TokenVerifier:
    if not settings.auth_configured:
        # Fail closed: an unconfigured API never lets a request through.
        logger.error("auth.not_configured")
        raise AuthUnavailableError("Authentication is not configured")
    assert settings.auth_issuer and settings.auth_audience and settings.auth_jwks_url
    return _cached_verifier(
        settings.auth_issuer,
        settings.auth_audience,
        settings.auth_jwks_url,
        tuple(settings.auth_allowed_algorithms),
        settings.auth_leeway_seconds,
        settings.auth_jwks_cache_seconds,
        settings.auth_jwks_min_refresh_seconds,
        settings.auth_jwks_timeout_seconds,
    )


def get_identity_service(session: DBSessionDep) -> IdentityService:
    return IdentityService(IdentityRepository(session))


def get_bearer_token(credentials: _BearerCredentials) -> str:
    """The raw bearer token, for the one thing that must forward it (A2A).
    Kept separate from `Principal` so the token cannot end up in logs or
    serialized objects by accident."""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()
    return credentials.credentials


async def get_current_principal(
    credentials: _BearerCredentials,
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    identities: Annotated[IdentityService, Depends(get_identity_service)],
) -> Principal:
    if credentials is None or not credentials.credentials:
        logger.info("auth.denied", reason="missing_credentials")
        raise UnauthorizedError()

    try:
        claims = await verifier.verify(credentials.credentials)
    except AuthKeysUnavailableError as exc:
        logger.error("auth.unavailable", reason=exc.reason)
        raise AuthUnavailableError() from exc
    except AuthError as exc:
        logger.info("auth.denied", reason=exc.reason)
        raise UnauthorizedError() from exc

    try:
        principal = await identities.resolve_principal(claims)
    except (IdentityNotLinkedError, AccountDisabledError) as exc:
        logger.info("auth.denied", reason=exc.reason)
        raise ForbiddenError() from exc
    except (SQLAlchemyError, OSError) as exc:
        logger.error("auth.unavailable", reason="identity_lookup_failed", error=type(exc).__name__)
        raise AuthUnavailableError() from exc

    structlog.contextvars.bind_contextvars(
        user_id=str(principal.user_id), organization_id=str(principal.organization_id)
    )
    return principal


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]
BearerTokenDep = Annotated[str, Depends(get_bearer_token)]


def require_admin(principal: PrincipalDep) -> Principal:
    if not principal.is_admin:
        logger.info("auth.denied", reason="admin_required")
        raise ForbiddenError()
    return principal


AdminDep = Annotated[Principal, Depends(require_admin)]
