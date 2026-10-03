"""Provider-neutral data structures for retrieval.

`RetrievalResult` is what crosses the `RetrievalStrategy`/`RetrievalService`
boundary — never a raw embedding vector, never an ORM object.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetrievalResult:
    """One candidate chunk, ranked by vector similarity.

    `distance` is the raw pgvector cosine distance (0 = identical, 2 =
    opposite); `similarity` is the same value converted to
    `1 - distance` (1 = identical, -1 = opposite) so callers never have to
    remember which direction is "better" for which metric — see ADR 007.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    distance: float
    similarity: float
    filename: str
    chunk_index: int
    page_number: int | None
    metadata: dict[str, Any] | None


@dataclass(frozen=True)
class RetrievalOutcome:
    """The full result of one retrieval call, before context assembly.

    `candidates` are the raw top-K nearest neighbors (for observability —
    "how many did the vector search even find"); `results` is the subset
    that passed `similarity_threshold` (what's actually usable). Keeping
    both lets callers log the funnel (candidates -> qualifying results ->
    chunks actually used in context) without re-deriving it later.
    """

    candidates: list[RetrievalResult]
    results: list[RetrievalResult]
    top_k: int
    similarity_threshold: float
    embedding_provider: str
    embedding_model: str
    embedding_model_version: str
