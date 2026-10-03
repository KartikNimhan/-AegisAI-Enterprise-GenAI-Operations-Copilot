"""Integration tests for DocumentRepository against real PostgreSQL.

Requires migrations to have been applied (`alembic upgrade head`). Skips
automatically if Postgres is unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.document_repository import DocumentRepository
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType

pytestmark = pytest.mark.integration


def make_document_kwargs(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "filename": f"{uuid.uuid4()}.txt",
        "original_filename": "report.txt",
        "content_type": "text/plain",
        "document_type": DocumentType.TXT,
        "file_size": 100,
        "checksum": uuid.uuid4().hex + uuid.uuid4().hex,  # 64 hex chars
        "status": DocumentStatus.UPLOADED,
    }
    defaults.update(overrides)
    return defaults


async def test_new_and_flush_assigns_id_and_timestamps(db_session: AsyncSession) -> None:
    repo = DocumentRepository(db_session)

    document = repo.new(**make_document_kwargs())
    await db_session.flush()

    assert document.id is not None
    assert document.created_at is not None
    assert document.updated_at is not None


async def test_get_returns_none_for_unknown_id(db_session: AsyncSession) -> None:
    repo = DocumentRepository(db_session)

    assert await repo.get(uuid.uuid4()) is None


async def test_get_by_checksum_finds_matching_document(db_session: AsyncSession) -> None:
    repo = DocumentRepository(db_session)
    checksum = uuid.uuid4().hex + uuid.uuid4().hex
    document = repo.new(**make_document_kwargs(checksum=checksum))
    await db_session.flush()

    found = await repo.get_by_checksum(checksum)

    assert found is not None
    assert found.id == document.id


async def test_get_by_checksum_returns_none_when_no_match(db_session: AsyncSession) -> None:
    repo = DocumentRepository(db_session)

    assert await repo.get_by_checksum("0" * 64) is None


async def test_list_returns_total_count_and_pagination(db_session: AsyncSession) -> None:
    repo = DocumentRepository(db_session)
    for _ in range(3):
        repo.new(**make_document_kwargs())
    await db_session.flush()

    page_one, total = await repo.list(limit=2, offset=0)
    page_two, total_again = await repo.list(limit=2, offset=2)

    assert total == 3
    assert total_again == 3
    assert len(page_one) == 2
    assert len(page_two) == 1


async def test_delete_removes_document(db_session: AsyncSession) -> None:
    repo = DocumentRepository(db_session)
    document = repo.new(**make_document_kwargs())
    await db_session.flush()

    deleted = await repo.delete(document.id)

    assert deleted is True
    assert await repo.get(document.id) is None


async def test_delete_returns_false_for_unknown_id(db_session: AsyncSession) -> None:
    repo = DocumentRepository(db_session)

    assert await repo.delete(uuid.uuid4()) is False


async def test_invalid_document_type_is_rejected_by_check_constraint(
    db_session: AsyncSession,
) -> None:
    repo = DocumentRepository(db_session)
    document = repo.new(**make_document_kwargs())
    await db_session.flush()

    # Bypass the Python enum entirely to exercise the DB-level constraint.
    with pytest.raises(DBAPIError, match="ck_documents_document_type"):
        await db_session.execute(
            text("UPDATE documents SET document_type = 'bogus' WHERE id = :id"),
            {"id": document.id},
        )
