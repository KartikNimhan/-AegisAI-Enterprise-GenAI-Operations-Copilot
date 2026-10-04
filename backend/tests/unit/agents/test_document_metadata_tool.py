"""Unit tests for the get_document_metadata tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.agents.tools.document_metadata import DocumentMetadataArgs, build_document_metadata_tool
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document

from ..services.document_doubles import FakeDocumentRepository


def make_document(**overrides: object) -> Document:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "filename": "internal-storage-key.pdf",
        "original_filename": "Travel Policy.pdf",
        "content_type": "application/pdf",
        "document_type": DocumentType.PDF,
        "file_size": 1234,
        "checksum": "a" * 64,
        "status": DocumentStatus.PROCESSED,
        "page_count": 3,
        "character_count": 500,
        "metadata_": {"paragraph_count": 10},
        "created_at": now,
        "updated_at": now,
        "processed_at": now,
    }
    defaults.update(overrides)
    return Document(**defaults)


async def test_returns_safe_metadata_for_an_existing_document() -> None:
    documents = FakeDocumentRepository()
    document = make_document()
    documents.documents[document.id] = document
    tool = build_document_metadata_tool(documents)  # type: ignore[arg-type]

    result = await tool.executor(DocumentMetadataArgs(document_id=document.id))

    assert result.success is True
    assert result.data is not None
    assert result.data["filename"] == "Travel Policy.pdf"
    assert result.data["document_type"] == "pdf"
    assert result.data["status"] == "processed"
    assert result.data["page_count"] == 3


async def test_never_exposes_internal_storage_key_or_checksum() -> None:
    documents = FakeDocumentRepository()
    document = make_document()
    documents.documents[document.id] = document
    tool = build_document_metadata_tool(documents)  # type: ignore[arg-type]

    result = await tool.executor(DocumentMetadataArgs(document_id=document.id))

    assert result.data is not None
    assert "internal-storage-key.pdf" not in str(result.data)
    assert "checksum" not in result.data
    assert "a" * 64 not in str(result.data)


async def test_missing_document_returns_not_found() -> None:
    documents = FakeDocumentRepository()
    tool = build_document_metadata_tool(documents)  # type: ignore[arg-type]

    result = await tool.executor(DocumentMetadataArgs(document_id=uuid.uuid4()))

    assert result.success is False
    assert result.error_code == "not_found"
