"""Internal orchestration results for `RAGService` — not the HTTP schemas
(those live in `app.api.schemas.rag` and are built from these)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from app.llm.schemas import StreamChunk, TokenUsage


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
    # True when the context budget cut this source's passage short before the model saw it
    # (`AssembledSource.passage_truncated`; only the first source can be cut).
    passage_truncated: bool
    # True when the (validated) answer text cites this source inline.
    cited: bool = False


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
    # The metadata filters that were applied (document id, type, filename, date range).
    filters: dict[str, Any] = field(default_factory=dict)


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
    # Citation ids the model wrote that were not among the retrieved sources; removed from `answer`.
    invalid_citations: tuple[str, ...] = ()
    # The saved assistant message (M10.4 T4): its citations are read through this id.
    message_id: uuid.UUID | None = None


class RAGStreamItem(NamedTuple):
    """One item of `RAGService.answer_stream` (M10.4 T4).

    `sources`, `invalid_citations` and `message_id` are None on every chunk except the final one.
    `message_id` is the id the assistant message WILL be saved under once the stream ends; the
    reply is saved only after the final chunk, so the id is valid only once the stream completes
    successfully (the HTTP stream ends with `[DONE]`)."""

    conversation_id: uuid.UUID
    chunk: StreamChunk
    sources: list[RAGSource] | None
    invalid_citations: tuple[str, ...] | None
    message_id: uuid.UUID | None
