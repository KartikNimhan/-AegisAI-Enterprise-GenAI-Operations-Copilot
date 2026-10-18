"""Maps a verified token to an internal principal.

Organization, role and active status always come from the database row for
the token's `(issuer, subject)` — never from token claims. A valid token for
an unknown identity is rejected (accounts are admin-created or invited; this
function never creates one).
"""

from __future__ import annotations

from typing import Protocol

from app.auth.exceptions import AccountDisabledError, IdentityNotLinkedError
from app.auth.principal import Principal
from app.auth.tokens import VerifiedClaims
from app.db.repositories.identity_repository import IdentityContext


class _IdentityLookup(Protocol):
    async def get_context(self, *, issuer: str, subject: str) -> IdentityContext | None: ...


class IdentityService:
    def __init__(self, identities: _IdentityLookup) -> None:
        self._identities = identities

    async def resolve_principal(self, claims: VerifiedClaims) -> Principal:
        context = await self._identities.get_context(issuer=claims.issuer, subject=claims.subject)
        if context is None:
            raise IdentityNotLinkedError("unknown_identity")
        if not context.user.is_active:
            raise AccountDisabledError("user_disabled")
        if not context.organization.is_active:
            raise AccountDisabledError("organization_disabled")
        return Principal(
            user_id=context.user.id,
            organization_id=context.organization.id,
            role=context.user.role,
            email=context.user.email,
            issuer=claims.issuer,
            token_id=claims.token_id,
        )
