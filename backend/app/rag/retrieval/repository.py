"""The RAG-specific retrieval query.

Deliberately separate from `app.db.repositories.chunk_embedding_repository`
(Milestone 4's generic similarity-search foundation): this repository adds
RAG-specific query shaping — joining through to `Document` for the
client-facing filename, and an explicit, narrow metadata-filter allowlist
(`RetrievalFilters`: document id, document type, filename, created-at range — see ADR 007 on
why this isn't a generic filter language). It still returns top-K nearest neighbors ordered by
distance with no threshold applied; similarity-threshold filtering is a
`RetrievalService`-level responsibility (see `retrieval/service.py`) so it
stays testable as plain Python, not buried in a query.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import AccessScope
from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk
from app.rag.retrieval.schemas import RetrievalFilters


class RetrievalRepository:
    def __init__(self, session: AsyncSession, scope: AccessScope) -> None:
        self._session = session
        self._scope = scope

    async def search(
        self,
        *,
        query_vector: list[float],
        model: str,
        model_version: str,
        top_k: int,
        document_id: uuid.UUID | None = None,
        filters: RetrievalFilters | None = None,
    ) -> list[tuple[ChunkEmbedding, DocumentChunk, Document, float]]:
        criteria = (filters or RetrievalFilters()).with_document_id(document_id)
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(ChunkEmbedding, DocumentChunk, Document, distance)
            .join(DocumentChunk, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(
                # Applied before the top-K limit: only documents the caller may read are ever
                # ranked. The optional `document_id` below narrows this further; it can never
                # widen it.
                self._scope.document_read_filter(Document),
                ChunkEmbedding.embedding_model == model,
                ChunkEmbedding.embedding_model_version == model_version,
            )
            .order_by(distance)
            .limit(top_k)
        )
        # Metadata filters narrow the already-scoped set; all values are bound parameters.
        if criteria.document_id is not None:
            stmt = stmt.where(Document.id == criteria.document_id)
        if criteria.document_types:
            stmt = stmt.where(Document.document_type.in_(sorted(criteria.document_types)))
        if criteria.filename is not None:
            stmt = stmt.where(Document.original_filename == criteria.filename)
        if criteria.created_after is not None:
            stmt = stmt.where(Document.created_at >= criteria.created_after)
        if criteria.created_before is not None:
            stmt = stmt.where(Document.created_at <= criteria.created_before)

        result = await self._session.execute(stmt)
        return [
            (embedding, chunk, document, dist) for embedding, chunk, document, dist in result.all()
        ]
