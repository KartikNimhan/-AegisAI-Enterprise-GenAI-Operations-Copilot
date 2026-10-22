"""Provider-neutral data structures for retrieval.

`RetrievalResult` is what crosses the `RetrievalStrategy`/`RetrievalService`
boundary — never a raw embedding vector, never an ORM object.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.domain.enums.document_type import DocumentType

MAX_FILTER_DOCUMENT_TYPES = len(DocumentType)


@dataclass(frozen=True)
class RetrievalFilters:
    """Narrowing criteria for one retrieval, over columns `Document` really has.

    Every field is optional and they combine with AND. Filters only ever narrow the candidate
    set: the caller's access scope is applied separately, in SQL, and cannot be widened by any
    value here (a `document_id` the caller cannot read simply matches nothing). Values are bound
    parameters in the repository, never interpolated.
    """

    document_id: uuid.UUID | None = None
    document_types: frozenset[DocumentType] | None = None
    filename: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None

    @property
    def is_empty(self) -> bool:
        return self == RetrievalFilters()

    def with_document_id(self, document_id: uuid.UUID | None) -> RetrievalFilters:
        return self if document_id is None else replace(self, document_id=document_id)

    def describe(self) -> dict[str, Any]:
        """The applied filters as plain values, for response metadata and logs (no content)."""
        applied: dict[str, Any] = {}
        if self.document_id is not None:
            applied["document_id"] = str(self.document_id)
        if self.document_types:
            applied["document_types"] = sorted(t.value for t in self.document_types)
        if self.filename is not None:
            applied["filename"] = self.filename
        if self.created_after is not None:
            applied["created_after"] = self.created_after.isoformat()
        if self.created_before is not None:
            applied["created_before"] = self.created_before.isoformat()
        return applied


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
    filters: RetrievalFilters = RetrievalFilters()
