"""Embedding orchestration.

Pipeline: load a document's chunks in bounded batches -> skip chunks
already embedded for the configured (model, version) -> embed the rest via
the provider -> validate dimensions -> persist, one `ChunkEmbedding` row
per (chunk, model, version).

Chunks are paged through `DocumentChunkRepository.list_by_document`
(`Settings.embedding_batch_size` chunks at a time) rather than loaded all
at once — a document with thousands of chunks never needs them all in
memory simultaneously.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Annotated

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.db.repositories.document_repository import DocumentRepository
from app.dependencies import DBSessionDep
from app.domain.enums.document_status import DocumentStatus
from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.base import EmbeddingProvider
from app.embeddings.exceptions import DocumentNotReadyError, EmbeddingProviderError
from app.embeddings.providers.local import get_local_embedding_provider
from app.embeddings.schemas import (
    BatchOutcome,
    EmbeddingJobResult,
    EmbeddingStatus,
    SimilarityMatch,
)

logger = structlog.get_logger(__name__)

_MAX_BACKOFF_SECONDS = 4.0


class EmbeddingService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        provider: EmbeddingProvider,
        documents: DocumentRepository,
        chunks: DocumentChunkRepository,
        embeddings: ChunkEmbeddingRepository,
    ) -> None:
        self._session = session
        self._settings = settings
        self._provider = provider
        self._documents = documents
        self._chunks = chunks
        self._embeddings = embeddings

    async def embed_document(self, document_id: uuid.UUID) -> EmbeddingJobResult:
        document = await self._documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")
        if document.status != DocumentStatus.PROCESSED:
            raise DocumentNotReadyError(
                f"Document {document_id} is {document.status.value!r}, not "
                f"{DocumentStatus.PROCESSED.value!r} — nothing to embed yet"
            )

        start = time.perf_counter()
        batch_size = self._settings.embedding_batch_size
        model, model_version = self._provider.model_name, self._provider.model_version

        total_chunks = 0
        embedded_count = 0
        skipped_count = 0
        failed_count = 0
        batch_count = 0
        offset = 0

        while True:
            page, total = await self._chunks.list_by_document(
                document_id, limit=batch_size, offset=offset
            )
            if offset == 0:
                total_chunks = total
            if not page:
                break

            batch_count += 1
            already_embedded = await self._embeddings.get_embedded_chunk_ids(
                [chunk.id for chunk in page], model=model, model_version=model_version
            )
            to_embed = [chunk for chunk in page if chunk.id not in already_embedded]
            skipped_count += len(page) - len(to_embed)

            if to_embed:
                outcome = await self._embed_batch_with_retry(to_embed)
                embedded_count += len(outcome.succeeded_chunk_ids)
                failed_count += len(outcome.failed_chunk_ids)

            offset += batch_size

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "document_embedding_completed",
            document_id=str(document_id),
            provider=self._provider.name,
            model=model,
            model_version=model_version,
            total_chunks=total_chunks,
            embedded_count=embedded_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            batch_count=batch_count,
            duration_ms=duration_ms,
        )
        return EmbeddingJobResult(
            document_id=document_id,
            provider=self._provider.name,
            model=model,
            model_version=model_version,
            dimension=self._provider.dimension,
            total_chunks=total_chunks,
            embedded_count=embedded_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            duration_ms=duration_ms,
            batch_count=batch_count,
        )

    async def _embed_batch_with_retry(self, chunks: list[DocumentChunk]) -> BatchOutcome:
        texts = [chunk.content for chunk in chunks]
        max_attempts = self._settings.embedding_max_retries + 1
        attempt = 0
        vectors: list[list[float]] | None = None

        while vectors is None:
            attempt += 1
            batch_start = time.perf_counter()
            try:
                vectors = await self._provider.embed_texts(texts)
            except EmbeddingProviderError as exc:
                duration_ms = round((time.perf_counter() - batch_start) * 1000, 2)
                if attempt >= max_attempts:
                    logger.warning(
                        "embedding_batch_failed",
                        chunk_count=len(chunks),
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        duration_ms=duration_ms,
                    )
                    return BatchOutcome(failed_chunk_ids=[chunk.id for chunk in chunks])
                delay = min(0.5 * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)
                logger.info(
                    "embedding_batch_retry",
                    chunk_count=len(chunks),
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)

        embeddings = [
            ChunkEmbedding(
                document_chunk_id=chunk.id,
                embedding=vector,
                embedding_provider=self._provider.name,
                embedding_model=self._provider.model_name,
                embedding_model_version=self._provider.model_version,
                embedding_dimension=self._provider.dimension,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

        try:
            async with self._session.begin_nested():
                await self._embeddings.add_all(embeddings)
        except Exception as exc:
            logger.warning(
                "embedding_persistence_failed",
                chunk_count=len(chunks),
                error_type=type(exc).__name__,
            )
            return BatchOutcome(failed_chunk_ids=[chunk.id for chunk in chunks])

        return BatchOutcome(succeeded_chunk_ids=[chunk.id for chunk in chunks])

    async def get_embedding_status(self, document_id: uuid.UUID) -> EmbeddingStatus:
        document = await self._documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")

        total_chunks = await self._chunks.count_by_document(document_id)
        embedded_chunks = await self._embeddings.count_for_document(
            document_id,
            model=self._provider.model_name,
            model_version=self._provider.model_version,
        )

        if total_chunks == 0:
            status = "no_chunks"
        elif embedded_chunks == 0:
            status = "not_started"
        elif embedded_chunks < total_chunks:
            status = "partial"
        else:
            status = "complete"

        return EmbeddingStatus(
            document_id=document_id,
            provider=self._provider.name,
            model=self._provider.model_name,
            model_version=self._provider.model_version,
            dimension=self._provider.dimension,
            total_chunks=total_chunks,
            embedded_chunks=embedded_chunks,
            status=status,
        )

    async def similarity_search(self, *, query_text: str, top_k: int = 5) -> list[SimilarityMatch]:
        """Foundation capability (Milestone 4, section 11) — proves
        text -> embedding -> vector storage -> vector similarity query.
        Not a RAG retrieval pipeline: no query rewriting, filtering, or
        reranking.
        """
        query_vector = await self._provider.embed_text(query_text)
        rows = await self._embeddings.similarity_search(
            query_vector=query_vector,
            model=self._provider.model_name,
            model_version=self._provider.model_version,
            top_k=top_k,
        )
        return [
            SimilarityMatch(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                content=chunk.content,
                distance=distance,
                provider=embedding.embedding_provider,
                model=embedding.embedding_model,
                model_version=embedding.embedding_model_version,
            )
            for embedding, chunk, distance in rows
        ]


def get_embedding_service(
    session: DBSessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[EmbeddingProvider, Depends(get_local_embedding_provider)],
) -> EmbeddingService:
    return EmbeddingService(
        session=session,
        settings=settings,
        provider=provider,
        documents=DocumentRepository(session),
        chunks=DocumentChunkRepository(session),
        embeddings=ChunkEmbeddingRepository(session),
    )
