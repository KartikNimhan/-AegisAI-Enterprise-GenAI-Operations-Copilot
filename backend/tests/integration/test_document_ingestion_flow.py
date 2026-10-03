"""End-to-end integration tests: real HTTP, real extractors (pypdf,
python-docx), real PostgreSQL persistence, and real filesystem storage
(isolated to a pytest tmp_path, never the project's actual upload
directory).

Uses httpx.AsyncClient (not the sync TestClient) for the same
cross-event-loop reason documented in test_chat_flow.py (Milestone 2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.domain.models.document import Document
from app.main import app
from app.storage.local import LocalFileStorage, get_document_storage

from ..document_fixtures import (
    make_corrupt_pdf_bytes,
    make_docx_bytes,
    make_markdown_bytes,
    make_pdf_bytes,
    make_txt_bytes,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(db_session: AsyncSession, tmp_path: Path) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    storage = LocalFileStorage(tmp_path / "uploads")
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_document_storage] = lambda: storage
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_document_storage, None)
        # DocumentService commits internally, twice per upload, by design
        # (see docs/architecture/decisions/005-document-ingestion.md) — so,
        # unlike ChatService in test_chat_flow.py, the shared db_session
        # fixture's rollback-at-teardown does NOT clean up what this test
        # created. Delete it explicitly (cascades to chunks via FK).
        await db_session.execute(delete(Document))
        await db_session.commit()


async def test_upload_and_process_txt(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("sample.txt", make_txt_bytes(), "text/plain")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "processed"
    assert body["document_type"] == "txt"
    assert body["character_count"] > 0

    chunks_response = await client.get(f"/api/v1/documents/{body['id']}/chunks")
    assert chunks_response.json()["total"] >= 1


async def test_upload_and_process_markdown(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("sample.md", make_markdown_bytes(), "text/markdown")},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "processed"
    assert response.json()["document_type"] == "markdown"


async def test_upload_and_process_docx(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={
            "file": (
                "sample.docx",
                make_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "processed"
    assert body["metadata"]["paragraph_count"] == 4


async def test_upload_and_process_pdf(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={
            "file": ("sample.pdf", make_pdf_bytes(text="Integration Test PDF"), "application/pdf")
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "processed"
    assert body["page_count"] == 1

    chunks_response = await client.get(f"/api/v1/documents/{body['id']}/chunks")
    chunk_content = chunks_response.json()["items"][0]["content"]
    assert "Integration Test PDF" in chunk_content


async def test_corrupt_pdf_is_marked_failed_but_still_retrievable(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("broken.pdf", make_corrupt_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 201  # upload itself succeeded
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"]

    # The record survives and is retrievable — processing failure doesn't
    # erase the upload.
    get_response = await client.get(f"/api/v1/documents/{body['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "failed"

    chunks_response = await client.get(f"/api/v1/documents/{body['id']}/chunks")
    assert chunks_response.json()["total"] == 0


async def test_duplicate_upload_returns_existing_document(client: AsyncClient) -> None:
    content = make_txt_bytes()

    first = await client.post("/api/v1/documents", files={"file": ("a.txt", content, "text/plain")})
    second = await client.post(
        "/api/v1/documents", files={"file": ("b.txt", content, "text/plain")}
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["is_duplicate"] is True
    assert second.json()["id"] == first.json()["id"]


async def test_delete_removes_document_file_and_chunks(client: AsyncClient, tmp_path: Path) -> None:
    upload = await client.post(
        "/api/v1/documents", files={"file": ("sample.txt", make_txt_bytes(), "text/plain")}
    )
    document_id = upload.json()["id"]
    stored_files_before = list((tmp_path / "uploads").iterdir())
    assert len(stored_files_before) == 1

    delete_response = await client.delete(f"/api/v1/documents/{document_id}")

    assert delete_response.status_code == 204
    assert list((tmp_path / "uploads").iterdir()) == []

    get_response = await client.get(f"/api/v1/documents/{document_id}")
    assert get_response.status_code == 404

    chunks_response = await client.get(f"/api/v1/documents/{document_id}/chunks")
    assert chunks_response.status_code == 404


async def test_list_documents_reflects_uploads(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/documents", files={"file": ("a.txt", make_txt_bytes(), "text/plain")}
    )
    await client.post(
        "/api/v1/documents",
        files={"file": ("b.txt", make_txt_bytes() + b" different", "text/plain")},
    )

    response = await client.get("/api/v1/documents")

    assert response.status_code == 200
    assert response.json()["total"] == 2


async def test_oversized_upload_is_rejected(client: AsyncClient) -> None:
    from app.config import Settings, get_settings

    tiny_limit_settings = Settings(document_max_upload_size_bytes=10)
    app.dependency_overrides[get_settings] = lambda: tiny_limit_settings
    try:
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("big.txt", b"well over ten bytes of content", "text/plain")},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "document_validation_error"
