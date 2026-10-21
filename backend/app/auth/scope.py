"""The data an authenticated caller may reach: the single source of the ownership
and organization predicates every business query applies.

Rules (see docs/architecture/decisions/013-data-isolation.md):

- **Conversations** (and so their messages) belong to one user. Only that user
  may read, continue or delete them. Administrators have no special access.
- **Documents** (and so their chunks and embeddings) belong to one user inside one
  organization. They are readable by the owner and, when their visibility is
  `organization`, by members of that organization; never across organizations.
  An administrator of the organization may *delete or re-share* any document in
  it, but may not read a private one.
- A row that is out of scope is reported as not found (404), never as forbidden,
  so a guessed id reveals nothing. A row with no owner yet (legacy data before the
  ownership backfill) matches no caller's scope and is therefore invisible.

Repositories take an `AccessScope` in their constructor, so a business query
cannot be written without one. The only unrestricted scope is for operator tools
(the evaluation harness, scripts, migrations' tests) and must never be built
inside `app.api` or `app.core`; a test enforces that.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import and_, false, or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.domain.enums.document_visibility import DocumentVisibility

if TYPE_CHECKING:
    from app.auth.principal import Principal
    from app.domain.models.conversation import Conversation
    from app.domain.models.document import Document


@dataclass(frozen=True)
class AccessScope:
    user_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    is_admin: bool = False
    unrestricted: bool = False

    @classmethod
    def from_principal(cls, principal: Principal) -> AccessScope:
        return cls(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            is_admin=principal.is_admin,
        )

    @classmethod
    def for_user(
        cls, *, user_id: uuid.UUID, organization_id: uuid.UUID, is_admin: bool = False
    ) -> AccessScope:
        return cls(user_id=user_id, organization_id=organization_id, is_admin=is_admin)

    @classmethod
    def unrestricted_for_operators(cls) -> AccessScope:
        """No filtering at all. For operator tooling only: never from a request."""
        return cls(user_id=None, organization_id=None, is_admin=False, unrestricted=True)

    # -- predicates ------------------------------------------------------------

    def conversation_filter(self, model: type[Conversation]) -> ColumnElement[bool]:
        if self.unrestricted:
            return true()
        if self.user_id is None:
            return false()
        return model.owner_user_id == self.user_id

    def document_read_filter(self, model: type[Document]) -> ColumnElement[bool]:
        """Rows the caller may read: their own, or organization-visible ones in
        their organization."""
        if self.unrestricted:
            return true()
        if self.user_id is None or self.organization_id is None:
            return false()
        return and_(
            model.organization_id == self.organization_id,
            or_(
                model.owner_user_id == self.user_id,
                model.visibility == DocumentVisibility.ORGANIZATION,
            ),
        )

    def document_manage_filter(self, model: type[Document]) -> ColumnElement[bool]:
        """Rows the caller may delete or re-share: their own, or (for an
        administrator) any in their organization. This does NOT imply read access."""
        if self.unrestricted:
            return true()
        if self.user_id is None or self.organization_id is None:
            return false()
        if self.is_admin:
            return model.organization_id == self.organization_id
        return and_(
            model.organization_id == self.organization_id,
            model.owner_user_id == self.user_id,
        )

    def document_summary_filter(self, model: type[Document]) -> ColumnElement[bool]:
        """Documents counted by the operations summary. A member's summary covers what they may
        read. An administrator's covers every document in their organization: the summary is
        aggregate numbers only (counts by processing status), never titles, owners or content,
        so it gives an administrator the operational picture of the organization they administer
        without letting them read a private document."""
        if self.unrestricted:
            return true()
        if self.is_admin and self.organization_id is not None:
            return model.organization_id == self.organization_id
        return self.document_read_filter(model)

    def document_owner_filter(self, model: type[Document]) -> ColumnElement[bool]:
        """Rows the caller owns: the scope for duplicate detection on upload."""
        if self.unrestricted:
            return true()
        if self.user_id is None:
            return false()
        return model.owner_user_id == self.user_id
