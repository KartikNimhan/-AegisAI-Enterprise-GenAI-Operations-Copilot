"""Provider-neutral data structures for embedding generation.

The provider interface itself (`base.py`) only deals in `list[list[float]]`
— a provider already knows its own name/model/version/dimension as
instance attributes, so nothing richer needs to travel through
`embed_texts`. These dataclasses are for `EmbeddingService`'s own
orchestration results and the similarity-search foundation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmbeddingJobResult:
    """Outcome of embedding one document's chunks."""

    document_id: uuid.UUID
    provider: str
    model: str
    model_version: str
    dimension: int
    total_chunks: int
    embedded_count: int
    skipped_count: int  # already had an embedding for this model/version
    failed_count: int
    duration_ms: float
    batch_count: int = 0


@dataclass(frozen=True)
class EmbeddingStatus:
    """Current embedding coverage for one document, for the configured
    (or a specified) model/version — never includes raw vectors."""

    document_id: uuid.UUID
    provider: str
    model: str
    model_version: str
    dimension: int
    total_chunks: int
    embedded_chunks: int
    status: str  # "not_started" | "partial" | "complete" | "no_chunks"


@dataclass(frozen=True)
class SimilarityMatch:
    """One result row from a similarity search — the foundation this
    milestone proves, not the RAG retrieval pipeline itself."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    distance: float
    provider: str
    model: str
    model_version: str


@dataclass(frozen=True)
class ChunkTextInput:
    """One chunk's text plus the id it should be persisted against — the
    unit `EmbeddingService` batches and passes to the provider."""

    chunk_id: uuid.UUID
    text: str


@dataclass(frozen=True)
class BatchOutcome:
    """Result of attempting to embed one batch of chunks."""

    succeeded_chunk_ids: list[uuid.UUID] = field(default_factory=list)
    failed_chunk_ids: list[uuid.UUID] = field(default_factory=list)
