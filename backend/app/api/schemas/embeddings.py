"""Request/response schemas for the embedding endpoints.

Never includes a raw vector — these responses report counts, status, and
model metadata only (Milestone 4, section 14).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.embeddings.schemas import EmbeddingJobResult, EmbeddingStatus


class EmbeddingTriggerResponse(BaseModel):
    document_id: uuid.UUID
    provider: str
    model: str
    model_version: str
    dimension: int
    total_chunks: int
    embedded_count: int
    skipped_count: int
    failed_count: int
    batch_count: int
    duration_ms: float

    @classmethod
    def from_result(cls, result: EmbeddingJobResult) -> EmbeddingTriggerResponse:
        return cls(
            document_id=result.document_id,
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            dimension=result.dimension,
            total_chunks=result.total_chunks,
            embedded_count=result.embedded_count,
            skipped_count=result.skipped_count,
            failed_count=result.failed_count,
            batch_count=result.batch_count,
            duration_ms=result.duration_ms,
        )


class EmbeddingStatusResponse(BaseModel):
    document_id: uuid.UUID
    provider: str
    model: str
    model_version: str
    dimension: int
    total_chunks: int
    embedded_chunks: int
    status: str

    @classmethod
    def from_status(cls, status_obj: EmbeddingStatus) -> EmbeddingStatusResponse:
        return cls(
            document_id=status_obj.document_id,
            provider=status_obj.provider,
            model=status_obj.model,
            model_version=status_obj.model_version,
            dimension=status_obj.dimension,
            total_chunks=status_obj.total_chunks,
            embedded_chunks=status_obj.embedded_chunks,
            status=status_obj.status,
        )
