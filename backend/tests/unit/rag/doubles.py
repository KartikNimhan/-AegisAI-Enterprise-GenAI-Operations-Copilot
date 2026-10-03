"""Test doubles for RAG unit tests (retrieval, context, service, API).

Not a test module itself (no `test_*` functions). None of these touch a
real database, model, or the real Groq SDK.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.llm.gateway import LLMGateway
from app.llm.schemas import ChatMessage, CompletionResponse, ModelRole, StreamChunk
from app.rag.retrieval.schemas import RetrievalResult
from app.rag.retrieval.strategy import RetrievalStrategy


def make_result(
    *,
    chunk_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    content: str = "some retrieved content",
    distance: float = 0.1,
    filename: str = "policy.pdf",
    chunk_index: int = 0,
    page_number: int | None = 4,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        content=content,
        distance=distance,
        similarity=1.0 - distance,
        filename=filename,
        chunk_index=chunk_index,
        page_number=page_number,
        metadata={"page_number": page_number} if page_number is not None else {},
    )


class FakeRetrievalStrategy(RetrievalStrategy):
    """Scripted: `search` always returns `results` regardless of the query,
    and records every call's arguments for assertions."""

    def __init__(
        self,
        *,
        results: list[RetrievalResult] | None = None,
        embedding_provider: str = "local",
        embedding_model: str = "fake-model",
        embedding_model_version: str = "1",
    ) -> None:
        self._results = results or []
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model
        self._embedding_model_version = embedding_model_version
        self.calls: list[dict[str, Any]] = []

    @property
    def embedding_provider(self) -> str:
        return self._embedding_provider

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    @property
    def embedding_model_version(self) -> str:
        return self._embedding_model_version

    async def search(
        self, *, query: str, top_k: int, document_id: uuid.UUID | None
    ) -> list[RetrievalResult]:
        self.calls.append({"query": query, "top_k": top_k, "document_id": document_id})
        return self._results[:top_k]


class ScriptedRAGGateway(LLMGateway):
    """Subclasses LLMGateway purely for type compatibility; `__init__`
    deliberately skips real settings/provider setup and overrides every
    method RAGService calls — mirrors `ScriptedChatGateway` in
    tests/unit/services/doubles.py."""

    def __init__(
        self,
        *,
        completion: CompletionResponse | None = None,
        completion_error: Exception | None = None,
        stream_chunks: list[StreamChunk] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self._completion = completion
        self._completion_error = completion_error
        self._stream_chunks = stream_chunks or []
        self._stream_error = stream_error
        self.chat_completion_calls: list[list[ChatMessage]] = []
        self.stream_calls: list[list[ChatMessage]] = []

    async def chat_completion(
        self, *, model_role: ModelRole, messages: list[ChatMessage], **kwargs: Any
    ) -> CompletionResponse:
        self.chat_completion_calls.append(messages)
        if self._completion_error is not None:
            raise self._completion_error
        assert self._completion is not None
        return self._completion

    async def stream_chat_completion(
        self, *, model_role: ModelRole, messages: list[ChatMessage], **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        self.stream_calls.append(messages)
        for chunk in self._stream_chunks:
            yield chunk
        if self._stream_error is not None:
            raise self._stream_error

    def model_metadata(self) -> dict[str, str]:
        return {"provider": "fake", "primary": "fake-model"}


class FakeDocumentRepositoryForRAG:
    """Minimal fake — RAGService only ever calls `.get()` on it, to
    validate a `document_id` filter exists."""

    def __init__(self, *, existing_ids: set[uuid.UUID] | None = None) -> None:
        self._existing_ids = existing_ids or set()

    async def get(self, document_id: uuid.UUID) -> object | None:
        return object() if document_id in self._existing_ids else None
