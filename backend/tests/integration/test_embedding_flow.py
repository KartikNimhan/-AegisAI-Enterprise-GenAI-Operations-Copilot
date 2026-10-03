"""End-to-end integration tests: real HTTP + real PostgreSQL persistence,
with a fake `EmbeddingProvider` (no real model download/inference needed).

Uses httpx.AsyncClient for the same cross-event-loop reason documented in
test_chat_flow.py/test_document_ingestion_flow.py. `EmbeddingService` never
commits internally (see app/embeddings/service.py) — it relies on the
request-scoped session's single commit, same as `ChatService` — so
overriding `get_session` with the shared, rollback-isolated `db_session`
fixture is enough; no explicit cleanup is needed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.document_repository import DocumentRepository
from app.db.session import get_session
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.chunk_embedding import EMBEDDING_DIMENSION
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.providers.local import get_local_embedding_provider
from app.main import app

from ..unit.services.embedding_doubles import FakeEmbeddingProvider

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    # The pgvector column is a fixed Vector(384) regardless of which
    # provider produced it (see app.domain.models.chunk_embedding) — a fake
    # provider used against the real schema must match that width.
    app.dependency_overrides[get_local_embedding_provider] = lambda: FakeEmbeddingProvider(
        name="local", model_name="fake-model", model_version="1", dimension=EMBEDDING_DIMENSION
    )
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_local_embedding_provider, None)


async def _make_processed_document_with_chunks(
    db_session: AsyncSession, *, chunk_count: int = 3
) -> uuid.UUID:
    repo = DocumentRepository(db_session)
    document = repo.new(
        filename=f"{uuid.uuid4()}.txt",
        original_filename="report.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        file_size=100,
        checksum=uuid.uuid4().hex + uuid.uuid4().hex,
        status=DocumentStatus.PROCESSED,
    )
    await db_session.flush()
    for i in range(chunk_count):
        db_session.add(
            DocumentChunk(
                id=uuid.uuid4(),
                document_id=document.id,
                chunk_index=i,
                content=f"chunk number {i}",
                character_count=20,
            )
        )
    await db_session.flush()
    return document.id


async def test_trigger_and_check_status_round_trip(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    document_id = await _make_processed_document_with_chunks(db_session, chunk_count=3)

    trigger_response = await client.post(f"/api/v1/documents/{document_id}/embeddings")
    assert trigger_response.status_code == 200
    body = trigger_response.json()
    assert body["document_id"] == str(document_id)
    assert body["total_chunks"] == 3
    assert body["embedded_count"] == 3
    assert body["failed_count"] == 0
    assert body["model"] == "fake-model"
    assert "embedding" not in body

    status_response = await client.get(f"/api/v1/documents/{document_id}/embeddings")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "complete"
    assert status_body["embedded_chunks"] == 3
    assert status_body["total_chunks"] == 3


async def test_triggering_twice_is_idempotent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    document_id = await _make_processed_document_with_chunks(db_session, chunk_count=2)

    first = await client.post(f"/api/v1/documents/{document_id}/embeddings")
    second = await client.post(f"/api/v1/documents/{document_id}/embeddings")

    assert first.json()["embedded_count"] == 2
    assert second.json()["embedded_count"] == 0
    assert second.json()["skipped_count"] == 2

    status_response = await client.get(f"/api/v1/documents/{document_id}/embeddings")
    assert status_response.json()["embedded_chunks"] == 2  # not duplicated


async def test_trigger_embeddings_for_unprocessed_document_returns_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
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

    response = await client.post(f"/api/v1/documents/{document.id}/embeddings")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "document_not_ready"


async def test_trigger_embeddings_for_unknown_document_returns_404(client: AsyncClient) -> None:
    response = await client.post(f"/api/v1/documents/{uuid.uuid4()}/embeddings")

    assert response.status_code == 404


async def test_status_for_document_with_no_chunks(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    document_id = await _make_processed_document_with_chunks(db_session, chunk_count=0)

    response = await client.get(f"/api/v1/documents/{document_id}/embeddings")

    assert response.status_code == 200
    assert response.json()["status"] == "no_chunks"
