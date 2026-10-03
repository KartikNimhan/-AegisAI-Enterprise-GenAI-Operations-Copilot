"""Unit tests for the document ingestion API endpoints.

The `DocumentService` dependency is overridden with a fake — no real
database, filesystem, or extraction library is involved.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk
from app.main import app
from app.services.document_service import (
    DocumentService,
    DocumentUploadResult,
    get_document_service,
)


def make_document(**overrides: object) -> Document:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "filename": "generated-key.txt",
        "original_filename": "report.txt",
        "content_type": "text/plain",
        "document_type": DocumentType.TXT,
        "file_size": 42,
        "checksum": "a" * 64,
        "status": DocumentStatus.PROCESSED,
        "character_count": 40,
        "created_at": now,
        "updated_at": now,
        "processed_at": now,
    }
    defaults.update(overrides)
    return Document(**defaults)


class FakeDocumentService(DocumentService):
    def __init__(
        self,
        *,
        upload_result: DocumentUploadResult | None = None,
        upload_error: Exception | None = None,
        documents: list[Document] | None = None,
        detail: Document | None = None,
        chunks: list[DocumentChunk] | None = None,
        chunks_exist: bool = True,
        deletable: bool = True,
    ) -> None:
        self._upload_result = upload_result
        self._upload_error = upload_error
        self._documents = documents or []
        self._detail = detail
        self._chunks = chunks or []
        self._chunks_exist = chunks_exist
        self._deletable = deletable

    async def upload(
        self, *, filename: str, content_type: str, content: bytes
    ) -> DocumentUploadResult:
        if self._upload_error is not None:
            raise self._upload_error
        assert self._upload_result is not None
        return self._upload_result

    async def list_documents(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[Document], int]:
        return self._documents[offset : offset + limit], len(self._documents)

    async def get_document(self, document_id: uuid.UUID) -> Document | None:
        return self._detail

    async def get_document_chunks(
        self, document_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[DocumentChunk], int] | None:
        if not self._chunks_exist:
            return None
        return self._chunks[offset : offset + limit], len(self._chunks)

    async def delete_document(self, document_id: uuid.UUID) -> bool:
        return self._deletable


@pytest.fixture
def override_document_service() -> Any:
    def _override(fake_service: DocumentService) -> None:
        app.dependency_overrides[get_document_service] = lambda: fake_service

    yield _override
    app.dependency_overrides.clear()


def test_upload_returns_201_for_a_new_document(
    client: TestClient, override_document_service: Any
) -> None:
    document = make_document()
    override_document_service(
        FakeDocumentService(
            upload_result=DocumentUploadResult(document=document, is_duplicate=False)
        )
    )

    response = client.post(
        "/api/v1/documents", files={"file": ("report.txt", b"hello world", "text/plain")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(document.id)
    assert body["filename"] == "report.txt"  # original_filename, not the storage key
    assert body["is_duplicate"] is False
    assert "metadata" in body


def test_upload_returns_200_for_a_duplicate(
    client: TestClient, override_document_service: Any
) -> None:
    document = make_document()
    override_document_service(
        FakeDocumentService(
            upload_result=DocumentUploadResult(document=document, is_duplicate=True)
        )
    )

    response = client.post(
        "/api/v1/documents", files={"file": ("report.txt", b"hello world", "text/plain")}
    )

    assert response.status_code == 200
    assert response.json()["is_duplicate"] is True


def test_upload_maps_validation_error_to_400(
    client: TestClient, override_document_service: Any
) -> None:
    from app.documents.exceptions import UnsupportedDocumentTypeError

    override_document_service(
        FakeDocumentService(upload_error=UnsupportedDocumentTypeError("Unsupported file extension"))
    )

    response = client.post(
        "/api/v1/documents", files={"file": ("virus.exe", b"x", "application/octet-stream")}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "document_validation_error"


def test_upload_requires_a_file(client: TestClient, override_document_service: Any) -> None:
    override_document_service(FakeDocumentService())

    response = client.post("/api/v1/documents")

    assert response.status_code == 422


def test_list_documents_returns_paginated_items(
    client: TestClient, override_document_service: Any
) -> None:
    docs = [make_document(original_filename=f"doc{i}.txt") for i in range(3)]
    override_document_service(FakeDocumentService(documents=docs))

    response = client.get("/api/v1/documents?limit=2&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_get_document_returns_detail(client: TestClient, override_document_service: Any) -> None:
    document = make_document()
    override_document_service(FakeDocumentService(detail=document))

    response = client.get(f"/api/v1/documents/{document.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(document.id)
    assert body["filename"] == "report.txt"  # original_filename, not the storage key
    assert "metadata" in body


def test_get_document_returns_404_when_missing(
    client: TestClient, override_document_service: Any
) -> None:
    override_document_service(FakeDocumentService(detail=None))

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_document_rejects_malformed_id(
    client: TestClient, override_document_service: Any
) -> None:
    override_document_service(FakeDocumentService())

    response = client.get("/api/v1/documents/not-a-uuid")

    assert response.status_code == 422


def test_get_document_chunks_returns_paginated_items(
    client: TestClient, override_document_service: Any
) -> None:
    document_id = uuid.uuid4()
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=document_id,
        chunk_index=0,
        content="hello",
        character_count=5,
        created_at=datetime.now(UTC),
    )
    override_document_service(FakeDocumentService(chunks=[chunk]))

    response = client.get(f"/api/v1/documents/{document_id}/chunks")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["content"] == "hello"


def test_get_document_chunks_returns_404_for_missing_document(
    client: TestClient, override_document_service: Any
) -> None:
    override_document_service(FakeDocumentService(chunks_exist=False))

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/chunks")

    assert response.status_code == 404


def test_delete_document_returns_204(client: TestClient, override_document_service: Any) -> None:
    override_document_service(FakeDocumentService(deletable=True))

    response = client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 204


def test_delete_document_returns_404_when_missing(
    client: TestClient, override_document_service: Any
) -> None:
    override_document_service(FakeDocumentService(deletable=False))

    response = client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 404
