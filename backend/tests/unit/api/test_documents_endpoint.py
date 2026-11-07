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
    OriginalFile,
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
        self.original: OriginalFile | None = None

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

    async def get_original_file(self, document_id: uuid.UUID) -> OriginalFile | None:
        return self.original


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


# -- M10.6: GET /documents/{id}/file ------------------------------------------


def _with_original(override_document_service: Any, original: OriginalFile | None) -> None:
    service = FakeDocumentService()
    service.original = original
    override_document_service(service)


def test_download_returns_the_original_as_an_attachment(
    client: TestClient, override_document_service: Any
) -> None:
    _with_original(
        override_document_service,
        OriginalFile(filename="report.pdf", media_type="application/pdf", content=b"%PDF-1.4 data"),
    )

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/file")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 data"
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="report.pdf"' in disposition
    assert "filename*=UTF-8''report.pdf" in disposition


def test_download_is_never_sniffed_cached_framed_or_run(
    client: TestClient, override_document_service: Any
) -> None:
    _with_original(
        override_document_service,
        OriginalFile(
            filename="a.txt", media_type="text/plain; charset=utf-8", content=b"<script>x</script>"
        ),
    )

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/file")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"


@pytest.mark.parametrize(
    ("name", "fallback", "encoded"),
    [
        ('evil"; filename=x.html', "evil__ filename_x.html", "evil%22%3B%20filename%3Dx.html"),
        ("a\r\nSet-Cookie: x=1.txt", "a__Set-Cookie_ x_1.txt", "a%0D%0ASet-Cookie%3A%20x%3D1.txt"),
        ("../../etc/passwd", "_.._etc_passwd", "..%2F..%2Fetc%2Fpasswd"),
        (
            "Bericht über Ärger.pdf",
            "Bericht _ber _rger.pdf",
            "Bericht%20%C3%BCber%20%C3%84rger.pdf",
        ),
        ("...", "document", "..."),
    ],
)
def test_download_filename_cannot_break_the_header(
    client: TestClient, override_document_service: Any, name: str, fallback: str, encoded: str
) -> None:
    _with_original(
        override_document_service,
        OriginalFile(filename=name, media_type="text/plain; charset=utf-8", content=b"x"),
    )

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/file")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition == f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
    assert "set-cookie" not in response.headers


def test_download_returns_404_when_not_readable(
    client: TestClient, override_document_service: Any
) -> None:
    _with_original(override_document_service, None)

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/file")

    assert response.status_code == 404
    assert "content-disposition" not in response.headers


def test_download_rejects_a_malformed_id(
    client: TestClient, override_document_service: Any
) -> None:
    override_document_service(FakeDocumentService())
    assert client.get("/api/v1/documents/not-a-uuid/file").status_code == 422
