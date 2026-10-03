"""Unit tests for the RAG chat API endpoints.

The `RAGService` dependency is overridden with a fake — no real retrieval,
database, model, or Groq call is involved.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import NotFoundError
from app.llm.exceptions import LLMError, LLMTimeoutError
from app.llm.schemas import StreamChunk, TokenUsage
from app.main import app
from app.rag.schemas import RAGAnswer, RAGRetrievalMetadata, RAGSource
from app.rag.service import RAGService, get_rag_service

_CONVERSATION_ID = uuid.uuid4()


def make_answer(**overrides: Any) -> RAGAnswer:
    defaults: dict[str, Any] = {
        "conversation_id": _CONVERSATION_ID,
        "answer": "Employees may claim travel expenses [S1].",
        "has_context": True,
        "sources": [
            RAGSource(
                source_id="S1",
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                filename="Travel Policy.pdf",
                chunk_index=0,
                page_number=4,
                similarity=0.82,
            )
        ],
        "retrieval": RAGRetrievalMetadata(
            top_k=5,
            similarity_threshold=0.3,
            candidates_found=3,
            chunks_used=1,
            context_truncated=False,
            embedding_provider="local",
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_model_version="1",
        ),
        "model": "openai/gpt-oss-120b",
        "provider": "groq",
        "usage": TokenUsage(input_tokens=50, output_tokens=10, total_tokens=60),
        "finish_reason": "stop",
        "request_id": "req_1",
    }
    defaults.update(overrides)
    return RAGAnswer(**defaults)


class FakeRAGService(RAGService):
    def __init__(
        self,
        *,
        answer_result: RAGAnswer | None = None,
        answer_error: Exception | None = None,
        stream_chunks: list[StreamChunk] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self._answer_result = answer_result
        self._answer_error = answer_error
        self._stream_chunks = stream_chunks or []
        self._stream_error = stream_error
        self.calls: list[dict[str, Any]] = []

    async def answer(
        self,
        *,
        conversation_id: uuid.UUID | None,
        message: str,
        model_role: Any,
        top_k: int | None = None,
        document_id: uuid.UUID | None = None,
    ) -> RAGAnswer:
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "message": message,
                "model_role": model_role,
                "top_k": top_k,
                "document_id": document_id,
            }
        )
        if self._answer_error is not None:
            raise self._answer_error
        assert self._answer_result is not None
        return self._answer_result

    async def answer_stream(
        self,
        *,
        conversation_id: uuid.UUID | None,
        message: str,
        model_role: Any,
        top_k: int | None = None,
        document_id: uuid.UUID | None = None,
    ) -> AsyncIterator[tuple[uuid.UUID, StreamChunk, list[RAGSource] | None]]:
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "message": message,
                "model_role": model_role,
                "top_k": top_k,
                "document_id": document_id,
            }
        )
        if self._stream_error is not None:
            raise self._stream_error
        resolved_id = conversation_id or _CONVERSATION_ID
        for i, chunk in enumerate(self._stream_chunks):
            is_last = i == len(self._stream_chunks) - 1
            sources = make_answer().sources if (is_last and chunk.is_final) else None
            yield resolved_id, chunk, sources


@pytest.fixture
def override_rag_service() -> Iterator[Any]:
    def _override(fake_service: RAGService) -> None:
        app.dependency_overrides[get_rag_service] = lambda: fake_service

    yield _override
    app.dependency_overrides.clear()


def test_rag_chat_returns_grounded_answer_with_sources(
    client: TestClient, override_rag_service: Any
) -> None:
    override_rag_service(FakeRAGService(answer_result=make_answer()))

    response = client.post("/api/v1/rag/chat", json={"message": "Can I claim travel expenses?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Employees may claim travel expenses [S1]."
    assert body["has_context"] is True
    assert body["sources"][0]["source_id"] == "S1"
    assert body["sources"][0]["page"] == 4
    assert body["retrieval"]["chunks_used"] == 1
    assert "embedding" not in body
    assert "vector" not in body


def test_rag_chat_returns_no_context_response(
    client: TestClient, override_rag_service: Any
) -> None:
    no_context_answer = make_answer(
        has_context=False,
        answer="I don't have enough information in the available documents to answer that.",
        sources=[],
        model=None,
        provider=None,
        usage=None,
        finish_reason=None,
        request_id=None,
    )
    override_rag_service(FakeRAGService(answer_result=no_context_answer))

    response = client.post("/api/v1/rag/chat", json={"message": "unanswerable question"})

    assert response.status_code == 200
    body = response.json()
    assert body["has_context"] is False
    assert body["sources"] == []
    assert body["model"] is None


def test_rag_chat_forwards_top_k_and_document_id(
    client: TestClient, override_rag_service: Any
) -> None:
    fake = FakeRAGService(answer_result=make_answer())
    override_rag_service(fake)
    document_id = uuid.uuid4()

    client.post(
        "/api/v1/rag/chat",
        json={"message": "question", "top_k": 3, "document_id": str(document_id)},
    )

    assert fake.calls[0]["top_k"] == 3
    assert fake.calls[0]["document_id"] == document_id


def test_rag_chat_rejects_empty_message(client: TestClient, override_rag_service: Any) -> None:
    override_rag_service(FakeRAGService(answer_result=make_answer()))

    response = client.post("/api/v1/rag/chat", json={"message": ""})

    assert response.status_code == 422


def test_rag_chat_rejects_top_k_above_the_hard_ceiling(
    client: TestClient, override_rag_service: Any
) -> None:
    override_rag_service(FakeRAGService(answer_result=make_answer()))

    response = client.post("/api/v1/rag/chat", json={"message": "q", "top_k": 1000})

    assert response.status_code == 422


def test_rag_chat_returns_404_for_unknown_document_filter(
    client: TestClient, override_rag_service: Any
) -> None:
    override_rag_service(FakeRAGService(answer_error=NotFoundError("Document not found")))

    response = client.post(
        "/api/v1/rag/chat", json={"message": "q", "document_id": str(uuid.uuid4())}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_rag_chat_returns_404_for_unknown_conversation(
    client: TestClient, override_rag_service: Any
) -> None:
    override_rag_service(FakeRAGService(answer_error=NotFoundError("Conversation not found")))

    response = client.post(
        "/api/v1/rag/chat", json={"message": "q", "conversation_id": str(uuid.uuid4())}
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (LLMTimeoutError("timed out", provider="groq"), 504, "llm_timeout"),
    ],
)
def test_rag_chat_maps_llm_errors_to_http_status(
    client: TestClient,
    override_rag_service: Any,
    error: LLMError,
    expected_status: int,
    expected_code: str,
) -> None:
    override_rag_service(FakeRAGService(answer_error=error))

    response = client.post("/api/v1/rag/chat", json={"message": "q"})

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code


def test_rag_chat_stream_emits_sse_events_with_sources_on_final_chunk(
    client: TestClient, override_rag_service: Any
) -> None:
    fake = FakeRAGService(
        stream_chunks=[
            StreamChunk(delta="Employees "),
            StreamChunk(delta="may claim.", is_final=True, finish_reason="stop"),
        ]
    )
    override_rag_service(fake)

    with client.stream("POST", "/api/v1/rag/chat/stream", json={"message": "q"}) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "Employees " in body
    assert "may claim." in body
    assert "[DONE]" in body
    assert "S1" in body  # sources appear somewhere in the final event
    assert str(_CONVERSATION_ID) in body


def test_rag_chat_stream_emits_error_event_on_failure(
    client: TestClient, override_rag_service: Any
) -> None:
    override_rag_service(FakeRAGService(stream_error=LLMTimeoutError("timed out", provider="groq")))

    with client.stream("POST", "/api/v1/rag/chat/stream", json={"message": "q"}) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "LLMTimeoutError" in body
    assert "[DONE]" not in body
