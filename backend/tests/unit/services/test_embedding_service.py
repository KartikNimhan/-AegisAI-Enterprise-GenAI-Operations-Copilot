"""Unit tests for EmbeddingService: orchestration against fakes — no real
database, model, or network call."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import Settings
from app.core.exceptions import NotFoundError
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.chunk_embedding import ChunkEmbedding
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings import service as service_module
from app.embeddings.exceptions import DocumentNotReadyError, EmbeddingProviderError
from app.embeddings.service import EmbeddingService

from .document_doubles import FakeDocumentRepository
from .embedding_doubles import (
    FakeChunkEmbeddingRepository,
    FakeDocumentChunkRepository,
    FakeEmbeddingProvider,
    FakeSession,
)


def make_document(**overrides: Any) -> Document:
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "filename": "generated-key.txt",
        "original_filename": "report.txt",
        "content_type": "text/plain",
        "document_type": DocumentType.TXT,
        "file_size": 42,
        "checksum": "a" * 64,
        "status": DocumentStatus.PROCESSED,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Document(**defaults)


def make_chunk(document_id: uuid.UUID, *, index: int, content: str = "chunk text") -> DocumentChunk:
    return DocumentChunk(
        id=uuid.uuid4(),
        document_id=document_id,
        chunk_index=index,
        content=content,
        character_count=len(content),
        created_at=datetime.now(UTC),
    )


def make_settings(*, embedding_batch_size: int = 50, embedding_max_retries: int = 2) -> Settings:
    return Settings(
        embedding_batch_size=embedding_batch_size,
        embedding_max_retries=embedding_max_retries,
    )


def make_service(
    *,
    document: Document | None,
    chunks: list[DocumentChunk] | None = None,
    settings: Settings | None = None,
    provider: FakeEmbeddingProvider | None = None,
    fail_add: bool = False,
    scripted_matches: list[tuple[ChunkEmbedding, DocumentChunk, float]] | None = None,
) -> tuple[
    EmbeddingService,
    FakeDocumentRepository,
    FakeDocumentChunkRepository,
    FakeChunkEmbeddingRepository,
]:
    documents = FakeDocumentRepository()
    if document is not None:
        documents.documents[document.id] = document
    chunk_repo = FakeDocumentChunkRepository(chunks or [])
    embedding_repo = FakeChunkEmbeddingRepository(
        chunks=chunk_repo, fail_add=fail_add, scripted_matches=scripted_matches
    )
    service = EmbeddingService(
        session=FakeSession(),  # type: ignore[arg-type]
        settings=settings or make_settings(),
        provider=provider or FakeEmbeddingProvider(),
        documents=documents,  # type: ignore[arg-type]
        chunks=chunk_repo,  # type: ignore[arg-type]
        embeddings=embedding_repo,  # type: ignore[arg-type]
    )
    return service, documents, chunk_repo, embedding_repo


async def test_embed_document_raises_not_found_for_unknown_document() -> None:
    service, *_rest = make_service(document=None)

    with pytest.raises(NotFoundError):
        await service.embed_document(uuid.uuid4())


async def test_embed_document_raises_not_ready_when_not_processed() -> None:
    document = make_document(status=DocumentStatus.UPLOADED)
    service, *_rest = make_service(document=document)

    with pytest.raises(DocumentNotReadyError):
        await service.embed_document(document.id)


async def test_embed_document_embeds_all_chunks_and_stamps_model_metadata() -> None:
    document = make_document()
    chunks = [make_chunk(document.id, index=i) for i in range(3)]
    provider = FakeEmbeddingProvider(
        name="local", model_name="fake-model", model_version="1", dimension=4
    )
    service, _documents, _chunks, embeddings = make_service(
        document=document, chunks=chunks, provider=provider
    )

    result = await service.embed_document(document.id)

    assert result.total_chunks == 3
    assert result.embedded_count == 3
    assert result.skipped_count == 0
    assert result.failed_count == 0
    assert len(embeddings.embeddings) == 3
    for row in embeddings.embeddings:
        assert row.embedding_provider == "local"
        assert row.embedding_model == "fake-model"
        assert row.embedding_model_version == "1"
        assert row.embedding_dimension == 4


async def test_embed_document_pages_chunks_in_configured_batch_size() -> None:
    document = make_document()
    chunks = [make_chunk(document.id, index=i) for i in range(5)]
    provider = FakeEmbeddingProvider(dimension=4)
    service, *_rest = make_service(
        document=document,
        chunks=chunks,
        provider=provider,
        settings=make_settings(embedding_batch_size=2),
    )

    result = await service.embed_document(document.id)

    assert result.total_chunks == 5
    assert result.embedded_count == 5
    assert result.batch_count == 3  # 2 + 2 + 1
    assert [len(call) for call in provider.calls] == [2, 2, 1]


async def test_embed_document_skips_chunks_already_embedded_for_model_and_version() -> None:
    document = make_document()
    chunks = [make_chunk(document.id, index=i) for i in range(2)]
    provider = FakeEmbeddingProvider(model_name="m", model_version="1", dimension=4)
    service, _documents, _chunks, embeddings = make_service(
        document=document, chunks=chunks, provider=provider
    )
    embeddings.embeddings.append(
        ChunkEmbedding(
            id=uuid.uuid4(),
            document_chunk_id=chunks[0].id,
            embedding=[0.0] * 4,
            embedding_provider="local",
            embedding_model="m",
            embedding_model_version="1",
            embedding_dimension=4,
        )
    )

    result = await service.embed_document(document.id)

    assert result.skipped_count == 1
    assert result.embedded_count == 1
    assert provider.calls == [[chunks[1].content]]


async def test_embed_document_retries_a_failed_batch_before_giving_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(service_module.asyncio, "sleep", no_sleep)

    document = make_document()
    chunks = [make_chunk(document.id, index=0)]
    provider = FakeEmbeddingProvider(
        dimension=4,
        effects=[EmbeddingProviderError("transient"), [[0.1, 0.2, 0.3, 0.4]]],
    )
    service, _documents, _chunks, embeddings = make_service(
        document=document,
        chunks=chunks,
        provider=provider,
        settings=make_settings(embedding_max_retries=1),
    )

    result = await service.embed_document(document.id)

    assert result.embedded_count == 1
    assert result.failed_count == 0
    assert len(provider.calls) == 2  # first attempt failed, retry succeeded
    assert len(embeddings.embeddings) == 1


async def test_embed_document_marks_batch_failed_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(service_module.asyncio, "sleep", no_sleep)

    document = make_document()
    chunks = [make_chunk(document.id, index=0)]
    provider = FakeEmbeddingProvider(
        dimension=4,
        effects=[EmbeddingProviderError("down"), EmbeddingProviderError("still down")],
    )
    service, *_rest = make_service(
        document=document,
        chunks=chunks,
        provider=provider,
        settings=make_settings(embedding_max_retries=1),
    )

    result = await service.embed_document(document.id)

    assert result.embedded_count == 0
    assert result.failed_count == 1
    assert len(provider.calls) == 2


async def test_embed_document_persistence_failure_marks_batch_failed_without_raising() -> None:
    document = make_document()
    chunks = [make_chunk(document.id, index=0)]
    service, *_rest = make_service(document=document, chunks=chunks, fail_add=True)

    result = await service.embed_document(document.id)

    assert result.embedded_count == 0
    assert result.failed_count == 1


async def test_get_embedding_status_raises_not_found_for_unknown_document() -> None:
    service, *_rest = make_service(document=None)

    with pytest.raises(NotFoundError):
        await service.get_embedding_status(uuid.uuid4())


async def test_get_embedding_status_no_chunks() -> None:
    document = make_document()
    service, *_rest = make_service(document=document, chunks=[])

    status = await service.get_embedding_status(document.id)

    assert status.status == "no_chunks"
    assert status.total_chunks == 0
    assert status.embedded_chunks == 0


async def test_get_embedding_status_not_started() -> None:
    document = make_document()
    chunks = [make_chunk(document.id, index=0)]
    service, *_rest = make_service(document=document, chunks=chunks)

    status = await service.get_embedding_status(document.id)

    assert status.status == "not_started"


async def test_get_embedding_status_partial_then_complete() -> None:
    document = make_document()
    chunks = [make_chunk(document.id, index=i) for i in range(2)]
    provider = FakeEmbeddingProvider(model_name="m", model_version="1", dimension=4)
    service, _documents, _chunks, embeddings = make_service(
        document=document, chunks=chunks, provider=provider
    )
    embeddings.embeddings.append(
        ChunkEmbedding(
            id=uuid.uuid4(),
            document_chunk_id=chunks[0].id,
            embedding=[0.0] * 4,
            embedding_provider="local",
            embedding_model="m",
            embedding_model_version="1",
            embedding_dimension=4,
        )
    )

    partial_status = await service.get_embedding_status(document.id)
    assert partial_status.status == "partial"
    assert partial_status.embedded_chunks == 1

    await service.embed_document(document.id)

    complete_status = await service.get_embedding_status(document.id)
    assert complete_status.status == "complete"
    assert complete_status.embedded_chunks == 2


async def test_similarity_search_embeds_query_and_delegates_to_repository() -> None:
    document = make_document()
    chunk = make_chunk(document.id, index=0, content="relevant content")
    embedding_row = ChunkEmbedding(
        id=uuid.uuid4(),
        document_chunk_id=chunk.id,
        embedding=[0.1, 0.2, 0.3, 0.4],
        embedding_provider="local",
        embedding_model="m",
        embedding_model_version="1",
        embedding_dimension=4,
    )
    provider = FakeEmbeddingProvider(model_name="m", model_version="1", dimension=4)
    service, *_rest = make_service(
        document=document,
        chunks=[chunk],
        provider=provider,
        scripted_matches=[(embedding_row, chunk, 0.05)],
    )

    matches = await service.similarity_search(query_text="a query", top_k=3)

    assert len(matches) == 1
    assert matches[0].chunk_id == chunk.id
    assert matches[0].document_id == document.id
    assert matches[0].content == "relevant content"
    assert matches[0].distance == 0.05
    assert matches[0].model == "m"
    assert provider.calls == [["a query"]]
