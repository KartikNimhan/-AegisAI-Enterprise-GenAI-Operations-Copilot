"""Internal orchestration results for `RAGService` — not the HTTP schemas
(those live in `app.api.schemas.rag` and are built from these)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.llm.schemas import TokenUsage


@dataclass(frozen=True)
class RAGSource:
    """One citation the answer may reference (e.g. "[S1]")."""

    source_id: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page_number: int | None
    similarity: float


@dataclass(frozen=True)
class RAGRetrievalMetadata:
    """Safe-to-return debugging/observability detail about how the answer
    was retrieved — never a raw vector, never document content."""

    top_k: int
    similarity_threshold: float
    candidates_found: int
    chunks_used: int
    context_truncated: bool
    embedding_provider: str
    embedding_model: str
    embedding_model_version: str


@dataclass(frozen=True)
class RAGAnswer:
    conversation_id: uuid.UUID
    answer: str
    has_context: bool
    sources: list[RAGSource]
    retrieval: RAGRetrievalMetadata
    model: str | None = None
    provider: str | None = None
    usage: TokenUsage | None = None
    finish_reason: str | None = None
    request_id: str | None = None
