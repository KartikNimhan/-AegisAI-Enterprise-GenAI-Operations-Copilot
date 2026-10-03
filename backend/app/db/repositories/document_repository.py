"""Persistence for `Document` entities."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.document import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def new(self, **kwargs: object) -> Document:
        """Builds and registers a new `Document` without flushing — callers
        that need the server-generated `created_at` immediately should
        flush themselves (see `DocumentService`, which controls the
        transaction boundary for the two-phase upload/processing flow)."""
        document = Document(**kwargs)
        self._session.add(document)
        return document

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def get_by_checksum(self, checksum: str) -> Document | None:
        result = await self._session.execute(
            select(Document).where(Document.checksum == checksum).order_by(Document.created_at)
        )
        return result.scalars().first()

    async def list(self, *, limit: int = 50, offset: int = 0) -> tuple[list[Document], int]:
        total = await self._session.scalar(select(func.count()).select_from(Document))
        # Tiebreak on id: two rows can land in the same timestamp tick,
        # which would otherwise make pagination order non-deterministic.
        result = await self._session.execute(
            select(Document)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total or 0

    async def delete(self, document_id: uuid.UUID) -> bool:
        document = await self._session.get(Document, document_id)
        if document is None:
            return False
        await self._session.delete(document)
        await self._session.flush()
        return True
