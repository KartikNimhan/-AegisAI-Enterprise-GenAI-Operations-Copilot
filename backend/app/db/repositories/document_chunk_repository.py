"""Persistence for `DocumentChunk` entities.

Chunks have no owner of their own: they belong to their document, so reads are
checked against the caller's `AccessScope` through that document.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import AccessScope
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk


class DocumentChunkRepository:
    def __init__(self, session: AsyncSession, scope: AccessScope) -> None:
        self._session = session
        self._scope = scope

    async def add_all(self, chunks: list[DocumentChunk]) -> None:
        self._session.add_all(chunks)
        await self._session.flush()

    async def list_by_document(
        self, document_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[DocumentChunk], int]:
        read = self._scope.document_read_filter(Document)
        total = await self._session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.document_id == document_id, read)
        )
        result = await self._session.execute(
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.document_id == document_id, read)
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total or 0

    async def get_readable_with_documents(
        self, references: list[tuple[uuid.UUID, uuid.UUID]]
    ) -> dict[uuid.UUID, tuple[DocumentChunk, Document]]:
        """The chunks the caller may read NOW, keyed by chunk id, for `(chunk_id, document_id)`
        references saved earlier (M10.4 citations). A chunk counts only if it still exists, still
        belongs to that same document, and that document passes the read filter today; anything
        else is simply absent, so a deleted, re-shared or foreign source is indistinguishable
        from a missing one. One query for all references.

        Matching is on the exact `(chunk_id, document_id)` pair (M10 review finding L1): two
        references to the same chunk with different documents do not collapse into one, so a
        reference naming the wrong document never borrows the right one's result. Callers must
        still compare the returned document with their own reference (`CitationService`)."""
        if not references:
            return {}
        wanted = set(references)
        result = await self._session.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.id.in_({chunk_id for chunk_id, _document_id in wanted}),
                self._scope.document_read_filter(Document),
            )
        )
        return {
            chunk.id: (chunk, document)
            for chunk, document in result.all()
            if (chunk.id, document.id) in wanted and chunk.document_id == document.id
        }

    async def list_readable_range(
        self, document_id: uuid.UUID, *, first_index: int, last_index: int
    ) -> list[DocumentChunk]:
        """Chunks `first_index..last_index` (inclusive) of a document the caller may read now,
        in order; empty if the document is not readable."""
        result = await self._session.execute(
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunk_index >= first_index,
                DocumentChunk.chunk_index <= last_index,
                self._scope.document_read_filter(Document),
            )
            .order_by(DocumentChunk.chunk_index)
        )
        return list(result.scalars().all())

    async def count_by_document(self, document_id: uuid.UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.document_id == document_id,
                self._scope.document_read_filter(Document),
            )
        )
        return total or 0
