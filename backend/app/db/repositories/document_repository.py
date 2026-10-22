"""Persistence for `Document` entities.

Every query applies the caller's `AccessScope` (see `app.auth.scope`): reads see
the caller's own documents and organization-visible ones in their organization;
deleting or re-sharing additionally allows an administrator of the organization.
A document outside the scope is simply "not found".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import AccessScope
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_visibility import DocumentVisibility
from app.domain.models.document import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession, scope: AccessScope) -> None:
        self._session = session
        self._scope = scope

    def new(self, **kwargs: object) -> Document:
        """Builds and registers a new `Document` without flushing — callers
        that need the server-generated `created_at` immediately should
        flush themselves (see `DocumentService`, which controls the
        transaction boundary for the two-phase upload/processing flow).

        The owner and organization come from the scope. A restricted scope refuses
        to create a document for anyone else; only an unrestricted (operator) scope
        may name the owner explicitly."""
        if not self._scope.unrestricted:
            if "owner_user_id" in kwargs or "organization_id" in kwargs:
                raise ValueError("owner_user_id / organization_id come from the access scope")
            if self._scope.user_id is None or self._scope.organization_id is None:
                raise ValueError("a document needs an owner")
            kwargs["owner_user_id"] = self._scope.user_id
            kwargs["organization_id"] = self._scope.organization_id
        document = Document(**kwargs)
        self._session.add(document)
        return document

    async def get(self, document_id: uuid.UUID) -> Document | None:
        """A document the caller may READ."""
        result = await self._session.execute(
            select(Document).where(
                Document.id == document_id, self._scope.document_read_filter(Document)
            )
        )
        return result.scalar_one_or_none()

    async def get_for_management(self, document_id: uuid.UUID) -> Document | None:
        """A document the caller may delete or re-share (its owner, or an
        administrator of its organization). This does not imply read access."""
        result = await self._session.execute(
            select(Document).where(
                Document.id == document_id, self._scope.document_manage_filter(Document)
            )
        )
        return result.scalar_one_or_none()

    async def lock_checksum(self, checksum: str) -> None:
        """Serializes concurrent uploads of the same bytes by the same user (PostgreSQL
        transaction-scoped advisory lock, released at commit/rollback). Without it two simultaneous
        uploads both pass the duplicate check and store the file twice: `checksum` is indexed but
        not unique (a unique index needs a data-dependent migration; see ADR 016). Other databases
        have no such lock, so this does nothing there. Different users, or different content, never
        wait on each other."""
        if self._scope.user_id is None:
            return
        bind = self._session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"document-upload:{self._scope.user_id}:{checksum}"},
        )

    async def get_by_checksum(self, checksum: str) -> Document | None:
        """The caller's OWN oldest document with this content. Duplicate detection never
        looks at anyone else's documents, so an upload cannot reveal that another user or
        organization holds the same bytes."""
        result = await self._session.execute(
            select(Document)
            .where(Document.checksum == checksum, self._scope.document_owner_filter(Document))
            .order_by(Document.created_at)
        )
        return result.scalars().first()

    async def list(self, *, limit: int = 50, offset: int = 0) -> tuple[list[Document], int]:
        read = self._scope.document_read_filter(Document)
        total = await self._session.scalar(select(func.count()).select_from(Document).where(read))
        # Tiebreak on id: two rows can land in the same timestamp tick,
        # which would otherwise make pagination order non-deterministic.
        result = await self._session.execute(
            select(Document)
            .where(read)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total or 0

    async def count_by_status(self) -> dict[DocumentStatus, int]:
        """A single grouped COUNT query — used by the Milestone 9 operations summary endpoint.
        A member's counts cover the documents they may read; an administrator's cover their whole
        organization (aggregate numbers only; see `AccessScope.document_summary_filter`). Only
        statuses with at least one row are present in the result; the caller fills in zero for
        the rest (see `app.api.v1.operations`)."""
        result = await self._session.execute(
            select(Document.status, func.count())
            .where(self._scope.document_summary_filter(Document))
            .group_by(Document.status)
        )
        return dict(result.all())  # type: ignore[arg-type]

    async def set_visibility(
        self, document_id: uuid.UUID, visibility: DocumentVisibility
    ) -> Document | None:
        document = await self.get_for_management(document_id)
        if document is None:
            return None
        document.visibility = visibility
        # Assigned explicitly (the project's convention, as in DocumentService): the column's
        # server-side `onupdate=func.now()` would otherwise leave `updated_at` expired after the
        # flush, and reading it in async code raises MissingGreenlet.
        document.updated_at = datetime.now(UTC)
        await self._session.flush()
        return document

    async def delete(self, document_id: uuid.UUID) -> bool:
        document = await self.get_for_management(document_id)
        if document is None:
            return False
        await self._session.delete(document)
        await self._session.flush()
        return True
