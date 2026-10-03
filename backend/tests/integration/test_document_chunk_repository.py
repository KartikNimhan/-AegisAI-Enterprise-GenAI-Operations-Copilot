"""Integration tests for DocumentChunkRepository against real PostgreSQL.

Requires migrations to have been applied. Skips automatically if Postgres
is unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.db.repositories.document_repository import DocumentRepository
from app.documents.chunk_ids import compute_chunk_id
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document_chunk import DocumentChunk

pytestmark = pytest.mark.integration


async def _make_document(db_session: AsyncSession):
    repo = DocumentRepository(db_session)
    document = repo.new(
        filename=f"{uuid.uuid4()}.txt",
        original_filename="report.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        file_size=100,
        checksum=uuid.uuid4().hex + uuid.uuid4().hex,
        status=DocumentStatus.UPLOADED,
    )
    await db_session.flush()
    return document


def _make_chunk(
    document_id: uuid.UUID, *, checksum: str, index: int, content: str
) -> DocumentChunk:
    return DocumentChunk(
        id=compute_chunk_id(
            document_checksum=checksum, chunk_size=1000, chunk_overlap=100, chunk_index=index
        ),
        document_id=document_id,
        chunk_index=index,
        content=content,
        character_count=len(content),
    )


async def test_add_all_persists_chunks(db_session: AsyncSession) -> None:
    document = await _make_document(db_session)
    repo = DocumentChunkRepository(db_session)
    chunks = [
        _make_chunk(document.id, checksum=document.checksum, index=0, content="first"),
        _make_chunk(document.id, checksum=document.checksum, index=1, content="second"),
    ]

    await repo.add_all(chunks)

    stored, total = await repo.list_by_document(document.id)
    assert total == 2
    assert [c.content for c in stored] == ["first", "second"]


async def test_list_by_document_orders_by_chunk_index(db_session: AsyncSession) -> None:
    document = await _make_document(db_session)
    repo = DocumentChunkRepository(db_session)
    # Insert out of order to confirm the query orders by chunk_index, not insertion order.
    chunks = [
        _make_chunk(document.id, checksum=document.checksum, index=2, content="third"),
        _make_chunk(document.id, checksum=document.checksum, index=0, content="first"),
        _make_chunk(document.id, checksum=document.checksum, index=1, content="second"),
    ]
    await repo.add_all(chunks)

    stored, _total = await repo.list_by_document(document.id)

    assert [c.content for c in stored] == ["first", "second", "third"]


async def test_count_by_document(db_session: AsyncSession) -> None:
    document = await _make_document(db_session)
    repo = DocumentChunkRepository(db_session)
    await repo.add_all(
        [_make_chunk(document.id, checksum=document.checksum, index=0, content="only one")]
    )

    assert await repo.count_by_document(document.id) == 1


async def test_duplicate_chunk_index_for_same_document_is_rejected(
    db_session: AsyncSession,
) -> None:
    document = await _make_document(db_session)
    repo = DocumentChunkRepository(db_session)
    await repo.add_all(
        [_make_chunk(document.id, checksum=document.checksum, index=0, content="first")]
    )

    with pytest.raises(IntegrityError):
        await repo.add_all(
            [_make_chunk(document.id, checksum=document.checksum, index=0, content="duplicate")]
        )


async def test_deleting_document_cascades_to_chunks(db_session: AsyncSession) -> None:
    document = await _make_document(db_session)
    chunk_repo = DocumentChunkRepository(db_session)
    document_repo = DocumentRepository(db_session)
    await chunk_repo.add_all(
        [_make_chunk(document.id, checksum=document.checksum, index=0, content="x")]
    )

    await document_repo.delete(document.id)

    assert await chunk_repo.count_by_document(document.id) == 0
