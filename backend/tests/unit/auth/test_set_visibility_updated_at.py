"""`DocumentRepository.set_visibility` stamps `updated_at` itself.

Regression: `Document.updated_at` has a server-side `onupdate=func.now()`. When only another column
is changed, SQLAlchemy leaves `updated_at` EXPIRED after the flush, and the API then reads it while
building the response; in async code that lazy load raises `MissingGreenlet` (CI failure in
tests/integration/test_data_isolation.py). The project's convention (see `DocumentService` and
`ConversationRepository.touch`) is to assign `updated_at` explicitly, which keeps it loaded.

MOCK-BASED: the session is a double, so this proves the repository assigns the value before the
flush, not that PostgreSQL behaves; the database-backed twin is the sharing tests in
tests/integration/test_data_isolation.py, which have not been run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.auth.scope import AccessScope
from app.db.repositories.document_repository import DocumentRepository
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.enums.document_visibility import DocumentVisibility
from app.domain.models.document import Document

OWNER = AccessScope.for_user(user_id=uuid.uuid4(), organization_id=uuid.uuid4())
LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


class _Result:
    def __init__(self, document: Document | None) -> None:
        self._document = document

    def scalar_one_or_none(self) -> Document | None:
        return self._document


class SessionWith:
    """Returns one document for every lookup, and records what the document looked like at flush."""

    def __init__(self, document: Document | None) -> None:
        self._document = document
        self.flushed_updated_at: list[datetime] = []

    async def execute(self, statement: Any) -> _Result:
        return _Result(self._document)

    async def flush(self) -> None:
        assert self._document is not None
        self.flushed_updated_at.append(self._document.updated_at)


def _document() -> Document:
    return Document(
        id=uuid.uuid4(),
        filename="key.txt",
        original_filename="policy.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        file_size=10,
        checksum="a" * 64,
        status=DocumentStatus.PROCESSED,
        visibility=DocumentVisibility.PRIVATE,
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
    )


async def test_updated_at_is_assigned_before_the_flush() -> None:
    document = _document()
    session = SessionWith(document)
    before = datetime.now(UTC)

    result = await DocumentRepository(session, OWNER).set_visibility(  # type: ignore[arg-type]
        document.id, DocumentVisibility.ORGANIZATION
    )

    assert result is document
    assert document.visibility == DocumentVisibility.ORGANIZATION
    assert before <= document.updated_at <= datetime.now(UTC) + timedelta(seconds=1)
    # It was already new when the flush happened, so nothing is left expired afterwards.
    assert session.flushed_updated_at == [document.updated_at]


async def test_updated_at_is_timezone_aware_utc_like_the_rest_of_the_project() -> None:
    document = _document()

    await DocumentRepository(SessionWith(document), OWNER).set_visibility(  # type: ignore[arg-type]
        document.id, DocumentVisibility.ORGANIZATION
    )

    assert document.updated_at.tzinfo is not None
    assert document.updated_at.utcoffset() == timedelta(0)


async def test_a_document_the_caller_cannot_manage_is_left_untouched() -> None:
    session = SessionWith(None)  # the scoped lookup finds nothing

    result = await DocumentRepository(session, OWNER).set_visibility(  # type: ignore[arg-type]
        uuid.uuid4(), DocumentVisibility.ORGANIZATION
    )

    assert result is None
    assert session.flushed_updated_at == []  # nothing was flushed
