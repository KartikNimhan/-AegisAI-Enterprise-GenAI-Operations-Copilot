"""Request/response schemas for the RAG chat endpoints.

Never includes a raw embedding vector. `top_k` is bounded at the schema
level (`le=50`) as a hard, request-shape-level ceiling independent of
`Settings.rag_max_results` — the service additionally clamps to the
configured ceiling, so a client can never request an unbounded number of
chunks even if the two limits are ever changed independently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums.document_type import DocumentType
from app.llm.schemas import ModelRole, TokenUsage
from app.rag.retrieval.schemas import RetrievalFilters
from app.rag.schemas import RAGAnswer, RAGRetrievalMetadata, RAGSource


class RAGChatRequest(BaseModel):
    message: str = Field(min_length=1, description="The user's question.")
    conversation_id: uuid.UUID | None = Field(
        default=None, description="Existing conversation to continue. Omit to start a new one."
    )
    model_role: ModelRole = ModelRole.PRIMARY
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Override the default number of chunks to retrieve. Capped server-side.",
    )
    document_id: uuid.UUID | None = Field(
        default=None, description="Restrict retrieval to a single document."
    )
    document_types: list[DocumentType] | None = Field(
        default=None,
        min_length=1,
        max_length=len(DocumentType),
        description="Restrict retrieval to documents of these types.",
    )
    filename: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Restrict retrieval to documents with exactly this original file name.",
    )
    created_after: datetime | None = Field(
        default=None,
        description="Only documents uploaded at or after this time (timezone required).",
    )
    created_before: datetime | None = Field(
        default=None,
        description="Only documents uploaded at or before this time (timezone required).",
    )

    @field_validator("created_after", "created_before")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("must include a timezone offset, e.g. 2026-01-01T00:00:00Z")
        return value

    @model_validator(mode="after")
    def _ordered_range(self) -> RAGChatRequest:
        if (
            self.created_after is not None
            and self.created_before is not None
            and self.created_after > self.created_before
        ):
            raise ValueError("created_after must not be later than created_before")
        return self

    def to_filters(self) -> RetrievalFilters:
        """The metadata filters other than `document_id` (which is passed on its own)."""
        return RetrievalFilters(
            document_types=frozenset(self.document_types) if self.document_types else None,
            filename=self.filename,
            created_after=self.created_after,
            created_before=self.created_before,
        )


class RAGSourceResponse(BaseModel):
    source_id: str
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page: int | None = None
    similarity: float
    cited: bool = False

    @classmethod
    def from_source(cls, source: RAGSource) -> RAGSourceResponse:
        return cls(
            source_id=source.source_id,
            document_id=source.document_id,
            filename=source.filename,
            chunk_index=source.chunk_index,
            page=source.page_number,
            similarity=source.similarity,
            cited=source.cited,
        )


class RAGRetrievalMetadataResponse(BaseModel):
    top_k: int
    similarity_threshold: float
    candidates_found: int
    chunks_used: int
    context_truncated: bool
    embedding_provider: str
    embedding_model: str
    embedding_model_version: str
    filters: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_metadata(cls, metadata: RAGRetrievalMetadata) -> RAGRetrievalMetadataResponse:
        return cls(
            top_k=metadata.top_k,
            similarity_threshold=metadata.similarity_threshold,
            candidates_found=metadata.candidates_found,
            chunks_used=metadata.chunks_used,
            context_truncated=metadata.context_truncated,
            embedding_provider=metadata.embedding_provider,
            embedding_model=metadata.embedding_model,
            embedding_model_version=metadata.embedding_model_version,
            filters=metadata.filters,
        )


class RAGChatResponse(BaseModel):
    conversation_id: uuid.UUID
    answer: str
    has_context: bool
    sources: list[RAGSourceResponse]
    retrieval: RAGRetrievalMetadataResponse
    model: str | None = None
    provider: str | None = None
    usage: TokenUsage | None = None
    finish_reason: str | None = None
    request_id: str | None = None
    invalid_citations: list[str] = Field(
        default_factory=list,
        description="Citation ids the model wrote that were not retrieved sources (removed).",
    )

    @classmethod
    def from_answer(cls, result: RAGAnswer) -> RAGChatResponse:
        return cls(
            conversation_id=result.conversation_id,
            answer=result.answer,
            has_context=result.has_context,
            sources=[RAGSourceResponse.from_source(s) for s in result.sources],
            retrieval=RAGRetrievalMetadataResponse.from_metadata(result.retrieval),
            model=result.model,
            provider=result.provider,
            usage=result.usage,
            finish_reason=result.finish_reason,
            request_id=result.request_id,
            invalid_citations=list(result.invalid_citations),
        )


class RAGChatStreamChunk(BaseModel):
    """One SSE `data:` payload for the streaming RAG endpoint.

    `sources` is populated only on the final chunk (`is_final=True`) —
    mirroring how `usage` is only populated on the final chunk of the plain
    chat stream — since sources come from retrieval, computed once before
    generation starts, not incrementally per token.
    """

    conversation_id: uuid.UUID
    delta: str
    model: str | None = None
    finish_reason: str | None = None
    is_final: bool = False
    usage: TokenUsage | None = None
    request_id: str | None = None
    sources: list[RAGSourceResponse] | None = None
