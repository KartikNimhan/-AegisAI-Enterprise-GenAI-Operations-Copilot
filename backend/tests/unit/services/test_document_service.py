"""Unit tests for DocumentService: the full ingestion pipeline against
fakes — no real database, filesystem, or network call."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.documents.exceptions import UnsupportedDocumentTypeError
from app.domain.enums.document_status import DocumentStatus
from app.services.document_service import DocumentService

from ...document_fixtures import make_corrupt_pdf_bytes, make_pdf_bytes, make_txt_bytes
from .document_doubles import (
    FakeDocumentChunkRepository,
    FakeDocumentRepository,
    FakeSession,
    FakeStorage,
)


def make_settings(
    *,
    document_chunk_size: int = 1000,
    document_chunk_overlap: int = 100,
    document_max_upload_size_bytes: int = 10_000,
    document_allowed_types: list[str] | None = None,
) -> Settings:
    return Settings(
        document_chunk_size=document_chunk_size,
        document_chunk_overlap=document_chunk_overlap,
        document_max_upload_size_bytes=document_max_upload_size_bytes,
        document_allowed_types=document_allowed_types or ["pdf", "docx", "txt", "markdown"],
    )


def make_service(
    *, settings: Settings | None = None, chunks_fail: bool = False
) -> tuple[
    DocumentService, FakeDocumentRepository, FakeDocumentChunkRepository, FakeStorage, FakeSession
]:
    session = FakeSession()
    documents = FakeDocumentRepository()
    chunks = FakeDocumentChunkRepository(fail_on_add=chunks_fail)
    storage = FakeStorage()
    service = DocumentService(
        session=session,  # type: ignore[arg-type]
        settings=settings or make_settings(),
        documents=documents,  # type: ignore[arg-type]
        chunks=chunks,  # type: ignore[arg-type]
        storage=storage,
    )
    return service, documents, chunks, storage, session


async def test_successful_upload_processes_and_persists() -> None:
    service, documents, chunks, storage, session = make_service()

    result = await service.upload(
        filename="sample.txt", content_type="text/plain", content=make_txt_bytes()
    )

    assert result.is_duplicate is False
    document = result.document
    assert document.status == DocumentStatus.PROCESSED
    assert document.error_message is None
    assert document.character_count is not None and document.character_count > 0
    assert len(chunks.chunks) >= 1
    assert all(c.document_id == document.id for c in chunks.chunks)
    assert await storage.exists(key=document.filename)
    assert session.commit_count == 2  # upload-phase commit + processing-phase commit


async def test_original_filename_is_preserved_but_storage_key_is_internal() -> None:
    service, *_rest = make_service()

    result = await service.upload(
        filename="my report.txt", content_type="text/plain", content=make_txt_bytes()
    )

    assert result.document.original_filename == "my report.txt"
    assert result.document.filename == f"{result.document.id}.txt"


async def test_duplicate_upload_returns_existing_document_without_reprocessing() -> None:
    service, documents, chunks, storage, session = make_service()
    content = make_txt_bytes()

    first = await service.upload(filename="a.txt", content_type="text/plain", content=content)
    chunk_count_after_first = len(chunks.chunks)
    commits_after_first = session.commit_count

    second = await service.upload(filename="b.txt", content_type="text/plain", content=content)

    assert second.is_duplicate is True
    assert second.document.id == first.document.id
    assert len(chunks.chunks) == chunk_count_after_first  # nothing new persisted
    assert session.commit_count == commits_after_first  # no additional commits


async def test_unsupported_extension_raises_before_any_storage_or_db_write() -> None:
    service, documents, chunks, storage, session = make_service()

    with pytest.raises(UnsupportedDocumentTypeError):
        await service.upload(
            filename="virus.exe", content_type="application/octet-stream", content=b"x"
        )

    assert documents.documents == {}
    assert storage.files == {}
    assert session.commit_count == 0


async def test_corrupt_file_results_in_failed_status_with_no_chunks() -> None:
    service, documents, chunks, storage, session = make_service()

    result = await service.upload(
        filename="broken.pdf", content_type="application/pdf", content=make_corrupt_pdf_bytes()
    )

    assert result.document.status == DocumentStatus.FAILED
    assert result.document.error_message is not None
    assert (
        "pdf" in result.document.error_message.lower()
        or "read" in result.document.error_message.lower()
    )
    assert chunks.chunks == []
    # The document record itself still exists (upload succeeded) —
    # processing failure doesn't erase the upload.
    assert result.document.id in documents.documents


async def test_failed_chunk_persistence_results_in_failed_status_with_no_chunks() -> None:
    service, documents, chunks, storage, session = make_service(chunks_fail=True)

    result = await service.upload(
        filename="sample.txt", content_type="text/plain", content=make_txt_bytes()
    )

    assert result.document.status == DocumentStatus.FAILED
    assert result.document.error_message == "Document processing failed due to an internal error"
    assert chunks.chunks == []
    assert session.commit_count == 2  # upload commit + failure-state commit


async def test_empty_extractable_text_is_marked_failed_not_processed() -> None:
    service, documents, chunks, storage, session = make_service()

    result = await service.upload(
        filename="empty.txt", content_type="text/plain", content=b"   \n\n  "
    )

    assert result.document.status == DocumentStatus.FAILED
    assert "no extractable text" in (result.document.error_message or "").lower()


async def test_pdf_upload_populates_page_count() -> None:
    service, *_rest = make_service()

    result = await service.upload(
        filename="doc.pdf", content_type="application/pdf", content=make_pdf_bytes()
    )

    assert result.document.status == DocumentStatus.PROCESSED
    assert result.document.page_count == 1


async def test_list_documents_returns_most_recent_first() -> None:
    service, *_rest = make_service()
    first = await service.upload(
        filename="a.txt", content_type="text/plain", content=make_txt_bytes()
    )
    second = await service.upload(
        filename="b.txt", content_type="text/plain", content=make_txt_bytes() + b" more"
    )

    items, total = await service.list_documents()

    assert total == 2
    assert items[0].id == second.document.id
    assert items[1].id == first.document.id


async def test_get_document_chunks_returns_none_for_unknown_document() -> None:
    service, *_rest = make_service()
    import uuid

    assert await service.get_document_chunks(uuid.uuid4()) is None


async def test_delete_document_removes_record_and_file() -> None:
    service, documents, chunks, storage, session = make_service()
    result = await service.upload(
        filename="a.txt", content_type="text/plain", content=make_txt_bytes()
    )

    deleted = await service.delete_document(result.document.id)

    assert deleted is True
    assert result.document.id not in documents.documents
    assert not await storage.exists(key=result.document.filename)


async def test_delete_document_returns_false_for_unknown_id() -> None:
    service, *_rest = make_service()
    import uuid

    assert await service.delete_document(uuid.uuid4()) is False
