"""The RAG-specific retrieval query.

Deliberately separate from `app.db.repositories.chunk_embedding_repository`
(Milestone 4's generic similarity-search foundation): this repository adds
RAG-specific query shaping — joining through to `Document` for the
client-facing filename, and an explicit, narrow metadata-filter allowlist
(`document_id` only, for now — see ADR 007 on why this isn't a generic
filter language). It still returns top-K nearest neighbors ordered by
distance with no threshold applied; similarity-threshold filtering is a
`RetrievalService`-level responsibility (see `retrieval/service.py`) so it
stays testable as plain Python, not buried in a query.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk


class RetrievalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        query_vector: list[float],
        model: str,
        model_version: str,
        top_k: int,
        document_id: uuid.UUID | None = None,
    ) -> list[tuple[ChunkEmbedding, DocumentChunk, Document, float]]:
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(ChunkEmbedding, DocumentChunk, Document, distance)
            .join(DocumentChunk, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(
                ChunkEmbedding.embedding_model == model,
                ChunkEmbedding.embedding_model_version == model_version,
            )
            .order_by(distance)
            .limit(top_k)
        )
        if document_id is not None:
            stmt = stmt.where(Document.id == document_id)

        result = await self._session.execute(stmt)
        return [
            (embedding, chunk, document, dist) for embedding, chunk, document, dist in result.all()
        ]
