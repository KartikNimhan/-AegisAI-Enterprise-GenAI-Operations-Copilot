"""Persistence for `ChunkEmbedding` entities, plus the similarity-search
foundation (Milestone 4, section 11) — exact pgvector distance queries,
not a RAG retrieval pipeline.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk


class ChunkEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, embeddings: list[ChunkEmbedding]) -> None:
        self._session.add_all(embeddings)
        await self._session.flush()

    async def get_embedded_chunk_ids(
        self, chunk_ids: list[uuid.UUID], *, model: str, model_version: str
    ) -> set[uuid.UUID]:
        """The idempotency check: which of these chunks already have an
        embedding for this exact (model, version)? `EmbeddingService` uses
        this to skip re-embedding them, not just to avoid wasted model
        calls but to never attempt the insert that the unique constraint
        would reject anyway."""
        if not chunk_ids:
            return set()
        result = await self._session.execute(
            select(ChunkEmbedding.document_chunk_id).where(
                ChunkEmbedding.document_chunk_id.in_(chunk_ids),
                ChunkEmbedding.embedding_model == model,
                ChunkEmbedding.embedding_model_version == model_version,
            )
        )
        return set(result.scalars().all())

    async def count_for_document(
        self, document_id: uuid.UUID, *, model: str, model_version: str
    ) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(ChunkEmbedding)
            .join(DocumentChunk, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
            .where(
                DocumentChunk.document_id == document_id,
                ChunkEmbedding.embedding_model == model,
                ChunkEmbedding.embedding_model_version == model_version,
            )
        )
        return total or 0

    async def similarity_search(
        self,
        *,
        query_vector: list[float],
        model: str,
        model_version: str,
        top_k: int = 5,
    ) -> list[tuple[ChunkEmbedding, DocumentChunk, float]]:
        """Exact (not approximate — no index yet, see ADR 006) cosine
        distance search, filtered to one model/version: mixing vectors
        from different embedding models in one ranking would be comparing
        incompatible vector spaces, not a meaningful similarity order."""
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(ChunkEmbedding, DocumentChunk, distance)
            .join(DocumentChunk, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
            .where(
                ChunkEmbedding.embedding_model == model,
                ChunkEmbedding.embedding_model_version == model_version,
            )
            .order_by(distance)
            .limit(top_k)
        )
        result = await self._session.execute(stmt)
        return [(embedding, chunk, dist) for embedding, chunk, dist in result.all()]
