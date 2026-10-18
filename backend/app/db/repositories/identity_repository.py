"""Identity queries: organization, user and external-identity rows.

Like every repository here it only flushes (never commits) — the caller's
session/transaction owns durability.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums.user_role import UserRole
from app.domain.models.organization import Organization
from app.domain.models.user import User
from app.domain.models.user_identity import UserIdentity


@dataclass(frozen=True)
class IdentityContext:
    user: User
    organization: Organization


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_context(self, *, issuer: str, subject: str) -> IdentityContext | None:
        result = await self._session.execute(
            select(User, Organization)
            .join(UserIdentity, UserIdentity.user_id == User.id)
            .join(Organization, Organization.id == User.organization_id)
            .where(UserIdentity.issuer == issuer, UserIdentity.subject == subject)
        )
        row = result.first()
        if row is None:
            return None
        return IdentityContext(user=row[0], organization=row[1])

    async def add_organization(self, *, name: str, is_active: bool = True) -> Organization:
        organization = Organization(name=name, is_active=is_active)
        self._session.add(organization)
        await self._session.flush()
        return organization

    async def add_user(
        self,
        *,
        organization_id: uuid.UUID,
        email: str,
        role: UserRole = UserRole.MEMBER,
        display_name: str | None = None,
        is_active: bool = True,
    ) -> User:
        user = User(
            organization_id=organization_id,
            email=email,
            role=role,
            display_name=display_name,
            is_active=is_active,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def link_identity(self, *, user_id: uuid.UUID, issuer: str, subject: str) -> UserIdentity:
        identity = UserIdentity(user_id=user_id, issuer=issuer, subject=subject)
        self._session.add(identity)
        await self._session.flush()
        return identity
