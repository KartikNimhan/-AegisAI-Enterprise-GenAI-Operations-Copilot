"""Request/response schemas for the RAG chat endpoints.

Never includes a raw embedding vector. `top_k` is bounded at the schema
level (`le=50`) as a hard, request-shape-level ceiling independent of
`Settings.rag_max_results` — the service additionally clamps to the
configured ceiling, so a client can never request an unbounded number of
chunks even if the two limits are ever changed independently.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.llm.schemas import ModelRole, TokenUsage
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


class RAGSourceResponse(BaseModel):
    source_id: str
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page: int | None = None
    similarity: float

    @classmethod
    def from_source(cls, source: RAGSource) -> RAGSourceResponse:
        return cls(
            source_id=source.source_id,
            document_id=source.document_id,
            filename=source.filename,
            chunk_index=source.chunk_index,
            page=source.page_number,
            similarity=source.similarity,
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
