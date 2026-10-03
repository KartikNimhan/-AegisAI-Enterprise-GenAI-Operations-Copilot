"""Retrieval strategies: how candidate chunks are found for a query.

`VectorRetrievalStrategy` (pure pgvector cosine-similarity search) is the
only implementation in this milestone. The interface exists so a future
hybrid strategy (vector + keyword/BM25) can be swapped in — or composed
alongside this one — without `RetrievalService` or anything above it
changing. See ADR 007, "Hybrid search foundation". This is deliberately
*not* a generic plugin system: one abstract method, one concrete class,
no registry — just the seam the brief asked for.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.service import EmbeddingService
from app.rag.retrieval.repository import RetrievalRepository
from app.rag.retrieval.schemas import RetrievalResult


class RetrievalStrategy(ABC):
    @property
    @abstractmethod
    def embedding_provider(self) -> str:
        """Identifies what produced the vectors this strategy searched
        against, for observability logging — "unknown"/"none" is a valid
        answer for a future non-vector strategy."""
        raise NotImplementedError

    @property
    @abstractmethod
    def embedding_model(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def embedding_model_version(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self, *, query: str, top_k: int, document_id: uuid.UUID | None
    ) -> list[RetrievalResult]:
        """Returns up to `top_k` candidates ordered by relevance
        (best first), unfiltered by any similarity threshold — that's
        `RetrievalService`'s job, not the strategy's.
        """
        raise NotImplementedError


class VectorRetrievalStrategy(RetrievalStrategy):
    """Embeds the query via `EmbeddingService` (never a raw
    `EmbeddingProvider` — see `app.rag.retrieval` module docs) and searches
    pgvector for nearest neighbors under the same embedding model/version
    used to embed the stored chunks. Comparing vectors from different
    models would be comparing incompatible vector spaces.
    """

    def __init__(
        self, *, embedding_service: EmbeddingService, repository: RetrievalRepository
    ) -> None:
        self._embedding_service = embedding_service
        self._repository = repository

    @property
    def embedding_provider(self) -> str:
        return self._embedding_service.provider_name

    @property
    def embedding_model(self) -> str:
        return self._embedding_service.model_name

    @property
    def embedding_model_version(self) -> str:
        return self._embedding_service.model_version

    async def search(
        self, *, query: str, top_k: int, document_id: uuid.UUID | None
    ) -> list[RetrievalResult]:
        query_vector = await self._embedding_service.embed_query(query)
        rows = await self._repository.search(
            query_vector=query_vector,
            model=self._embedding_service.model_name,
            model_version=self._embedding_service.model_version,
            top_k=top_k,
            document_id=document_id,
        )
        return [
            _to_result(chunk, document, distance) for _embedding, chunk, document, distance in rows
        ]


def _to_result(chunk: DocumentChunk, document: Document, distance: float) -> RetrievalResult:
    page_number = chunk.metadata_.get("page_number") if chunk.metadata_ else None
    return RetrievalResult(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        content=chunk.content,
        distance=distance,
        similarity=1.0 - distance,
        filename=document.original_filename,
        chunk_index=chunk.chunk_index,
        page_number=page_number,
        metadata=chunk.metadata_,
    )
