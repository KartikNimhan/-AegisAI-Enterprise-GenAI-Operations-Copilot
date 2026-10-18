"""The authenticated caller, as the rest of the application sees it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.enums.user_role import UserRole


@dataclass(frozen=True)
class Principal:
    """Built only from the database row for a verified token — never from
    token claims. Deliberately does NOT hold the raw bearer token (so it
    cannot be logged or serialized by accident); code that must forward the
    token (A2A) uses `app.core.security.BearerTokenDep` instead."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: UserRole
    email: str
    issuer: str
    token_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN
