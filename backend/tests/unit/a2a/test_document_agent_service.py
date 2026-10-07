"""Unit tests for `DocumentAgentService`: found/missing document ids,
safe-field-only output, and the deterministic (no LLM) summary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.a2a.document_agent import DocumentAgentService
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document

from ..services.document_doubles import FakeDocumentRepository


def _make_document(**overrides: object) -> Document:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "filename": "internal-key.pdf",
        "original_filename": "Policy.pdf",
        "content_type": "application/pdf",
        "document_type": DocumentType.PDF,
        "file_size": 100,
        "checksum": "a" * 64,
        "status": DocumentStatus.PROCESSED,
        "page_count": 3,
        "character_count": 500,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Document(**defaults)  # type: ignore[arg-type]


async def test_single_known_document_returns_safe_metadata() -> None:
    document = _make_document()
    repository = FakeDocumentRepository()
    repository.documents[document.id] = document
    service = DocumentAgentService(documents=repository)  # type: ignore[arg-type]

    result = await service.analyze(document_ids=[document.id])

    assert result.status == "completed"
    assert len(result.documents) == 1
    assert result.documents[0].filename == "Policy.pdf"
    assert result.documents[0].status == "processed"


async def test_unknown_document_id_is_a_failure_not_a_crash() -> None:
    repository = FakeDocumentRepository()
    service = DocumentAgentService(documents=repository)  # type: ignore[arg-type]

    result = await service.analyze(document_ids=[uuid.uuid4()])

    assert result.status == "failed"
    assert result.error is not None


async def test_mixed_known_and_unknown_ids_returns_partial_success() -> None:
    document = _make_document()
    repository = FakeDocumentRepository()
    repository.documents[document.id] = document
    service = DocumentAgentService(documents=repository)  # type: ignore[arg-type]

    result = await service.analyze(document_ids=[document.id, uuid.uuid4()])

    assert result.status == "completed"
    assert len(result.documents) == 1
    assert "Could not find" in result.answer


async def test_no_document_ids_is_a_failure() -> None:
    repository = FakeDocumentRepository()
    service = DocumentAgentService(documents=repository)  # type: ignore[arg-type]

    result = await service.analyze(document_ids=[])

    assert result.status == "failed"


async def test_result_never_exposes_checksum_or_internal_fields() -> None:
    document = _make_document()
    repository = FakeDocumentRepository()
    repository.documents[document.id] = document
    service = DocumentAgentService(documents=repository)  # type: ignore[arg-type]

    result = await service.analyze(document_ids=[document.id])

    reference = result.documents[0]
    assert not hasattr(reference, "checksum")
    assert not hasattr(reference, "filename_internal")
