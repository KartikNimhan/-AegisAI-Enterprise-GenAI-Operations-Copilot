"""A throwaway owner for the evaluation corpus.

Documents must have an owner, and every business repository applies an access scope.
The evaluation harness seeds its synthetic corpus inside a transaction that is
always rolled back, so it creates a throwaway organization and user in that same
transaction and evaluates retrieval exactly as that user would see it: the real
scoped code path, not a bypass.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import AccessScope
from app.domain.enums.user_role import UserRole
from app.domain.models.organization import Organization
from app.domain.models.user import User


async def create_evaluation_scope(session: AsyncSession) -> AccessScope:
    """Flushes (never commits) a new organization and member user; returns their scope.

    The ids are assigned here rather than by the database so the scope is complete before
    anything is flushed."""
    suffix = uuid.uuid4().hex
    organization = Organization(id=uuid.uuid4(), name=f"evaluation-{suffix}", is_active=True)
    user = User(
        id=uuid.uuid4(),
        organization_id=organization.id,
        email=f"evaluation-{suffix}@example.invalid",
        role=UserRole.MEMBER,
        is_active=True,
    )
    session.add(organization)
    session.add(user)
    await session.flush()
    return AccessScope.for_user(user_id=user.id, organization_id=organization.id)
