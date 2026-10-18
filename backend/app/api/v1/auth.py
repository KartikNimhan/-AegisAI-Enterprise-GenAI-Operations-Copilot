"""Authentication endpoints (Milestone 12, Phase 1a).

Only `GET /auth/me` for now — the authenticated caller's own identity, useful
as the post-sign-in check. Invitation redemption is Phase 1b.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.security import PrincipalDep
from app.domain.enums.user_role import UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


class MeResponse(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: UserRole


@router.get("/me", response_model=MeResponse)
async def get_me(principal: PrincipalDep) -> MeResponse:
    return MeResponse(
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        email=principal.email,
        role=principal.role,
    )
