"""Unit tests for the document embedding API endpoints.

The `EmbeddingService` dependency is overridden with a fake — no real
database, model, or network call is involved.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.embeddings.exceptions import DocumentNotReadyError
from app.embeddings.schemas import EmbeddingJobResult, EmbeddingStatus
from app.embeddings.service import EmbeddingService, get_embedding_service
from app.main import app


def make_result(**overrides: Any) -> EmbeddingJobResult:
    defaults: dict[str, Any] = {
        "document_id": uuid.uuid4(),
        "provider": "local",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "model_version": "1",
        "dimension": 384,
        "total_chunks": 3,
        "embedded_count": 3,
        "skipped_count": 0,
        "failed_count": 0,
        "duration_ms": 12.5,
        "batch_count": 1,
    }
    defaults.update(overrides)
    return EmbeddingJobResult(**defaults)


def make_status(**overrides: Any) -> EmbeddingStatus:
    defaults: dict[str, Any] = {
        "document_id": uuid.uuid4(),
        "provider": "local",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "model_version": "1",
        "dimension": 384,
        "total_chunks": 3,
        "embedded_chunks": 3,
        "status": "complete",
    }
    defaults.update(overrides)
    return EmbeddingStatus(**defaults)


class FakeEmbeddingService(EmbeddingService):
    def __init__(
        self,
        *,
        embed_result: EmbeddingJobResult | None = None,
        embed_error: Exception | None = None,
        status_result: EmbeddingStatus | None = None,
        status_error: Exception | None = None,
    ) -> None:
        self._embed_result = embed_result
        self._embed_error = embed_error
        self._status_result = status_result
        self._status_error = status_error

    async def embed_document(self, document_id: uuid.UUID) -> EmbeddingJobResult:
        if self._embed_error is not None:
            raise self._embed_error
        assert self._embed_result is not None
        return self._embed_result

    async def get_embedding_status(self, document_id: uuid.UUID) -> EmbeddingStatus:
        if self._status_error is not None:
            raise self._status_error
        assert self._status_result is not None
        return self._status_result


@pytest.fixture
def override_embedding_service() -> Any:
    def _override(fake_service: EmbeddingService) -> None:
        app.dependency_overrides[get_embedding_service] = lambda: fake_service

    yield _override
    app.dependency_overrides.clear()


def test_trigger_embeddings_returns_job_result(
    client: TestClient, override_embedding_service: Any
) -> None:
    document_id = uuid.uuid4()
    result = make_result(document_id=document_id)
    override_embedding_service(FakeEmbeddingService(embed_result=result))

    response = client.post(f"/api/v1/documents/{document_id}/embeddings")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(document_id)
    assert body["embedded_count"] == 3
    assert body["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    # Never returns raw vectors.
    assert "embedding" not in body
    assert "vector" not in body


def test_trigger_embeddings_returns_404_for_unknown_document(
    client: TestClient, override_embedding_service: Any
) -> None:
    from app.core.exceptions import NotFoundError

    override_embedding_service(
        FakeEmbeddingService(embed_error=NotFoundError("Document not found"))
    )

    response = client.post(f"/api/v1/documents/{uuid.uuid4()}/embeddings")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_trigger_embeddings_returns_400_when_document_not_processed(
    client: TestClient, override_embedding_service: Any
) -> None:
    override_embedding_service(
        FakeEmbeddingService(embed_error=DocumentNotReadyError("Document is 'uploaded'"))
    )

    response = client.post(f"/api/v1/documents/{uuid.uuid4()}/embeddings")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "document_not_ready"


def test_get_embedding_status_returns_status(
    client: TestClient, override_embedding_service: Any
) -> None:
    document_id = uuid.uuid4()
    status_obj = make_status(document_id=document_id, status="partial", embedded_chunks=1)
    override_embedding_service(FakeEmbeddingService(status_result=status_obj))

    response = client.get(f"/api/v1/documents/{document_id}/embeddings")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(document_id)
    assert body["status"] == "partial"
    assert body["embedded_chunks"] == 1
    assert "embedding" not in body


def test_get_embedding_status_returns_404_for_unknown_document(
    client: TestClient, override_embedding_service: Any
) -> None:
    from app.core.exceptions import NotFoundError

    override_embedding_service(
        FakeEmbeddingService(status_error=NotFoundError("Document not found"))
    )

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/embeddings")

    assert response.status_code == 404


def test_trigger_embeddings_rejects_malformed_document_id(
    client: TestClient, override_embedding_service: Any
) -> None:
    override_embedding_service(FakeEmbeddingService())

    response = client.post("/api/v1/documents/not-a-uuid/embeddings")

    assert response.status_code == 422
