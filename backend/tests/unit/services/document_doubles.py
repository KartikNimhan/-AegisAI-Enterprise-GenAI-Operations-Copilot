"""Test doubles for DocumentService unit tests.

Not a test module itself (no `test_*` functions). None of these touch a
real database or filesystem.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk
from app.storage.base import DocumentStorage


class _FakeNestedTransaction:
    async def __aenter__(self) -> _FakeNestedTransaction:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False  # never suppress — mirrors a real SAVEPOINT on error


class FakeSession:
    """Stand-in for AsyncSession — only what DocumentService calls directly."""

    def __init__(self) -> None:
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    def begin_nested(self) -> _FakeNestedTransaction:
        return _FakeNestedTransaction()


class FakeDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[uuid.UUID, Document] = {}
        # Strictly increasing, independent of wall-clock resolution — two
        # uploads in the same test can otherwise complete within the same
        # microsecond and make "most recent first" ordering ambiguous.
        self._clock = datetime.now(UTC)

    def new(self, **kwargs: Any) -> Document:
        document = Document(**kwargs)
        # Mimic what a real flush (server/Python-side defaults) would do.
        if document.id is None:
            document.id = uuid.uuid4()
        self._clock += timedelta(microseconds=1)
        if document.created_at is None:
            document.created_at = self._clock
        if document.updated_at is None:
            document.updated_at = self._clock
        self.documents[document.id] = document
        return document

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return self.documents.get(document_id)

    async def get_by_checksum(self, checksum: str) -> Document | None:
        for document in self.documents.values():
            if document.checksum == checksum:
                return document
        return None

    async def list(self, *, limit: int = 50, offset: int = 0) -> tuple[list[Document], int]:
        items = sorted(self.documents.values(), key=lambda d: d.created_at, reverse=True)
        return items[offset : offset + limit], len(items)

    async def delete(self, document_id: uuid.UUID) -> bool:
        return self.documents.pop(document_id, None) is not None


class FakeDocumentChunkRepository:
    def __init__(self, *, fail_on_add: bool = False) -> None:
        self.chunks: list[DocumentChunk] = []
        self._fail_on_add = fail_on_add

    async def add_all(self, chunks: list[DocumentChunk]) -> None:
        if self._fail_on_add:
            raise RuntimeError("Simulated chunk persistence failure")
        self.chunks.extend(chunks)

    async def list_by_document(
        self, document_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[DocumentChunk], int]:
        matching = [c for c in self.chunks if c.document_id == document_id]
        return matching[offset : offset + limit], len(matching)

    async def count_by_document(self, document_id: uuid.UUID) -> int:
        return sum(1 for c in self.chunks if c.document_id == document_id)


class FakeStorage(DocumentStorage):
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, *, key: str, content: bytes) -> None:
        self.files[key] = content

    async def read(self, *, key: str) -> bytes:
        return self.files[key]

    async def delete(self, *, key: str) -> None:
        self.files.pop(key, None)

    async def exists(self, *, key: str) -> bool:
        return key in self.files
