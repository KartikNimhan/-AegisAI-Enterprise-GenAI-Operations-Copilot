"""Integration tests for ChunkEmbeddingRepository against real PostgreSQL
with pgvector.

Requires migrations to have been applied. Skips automatically if Postgres
is unreachable. Uses small hand-crafted vectors, not the real embedding
model — see tests/integration/test_embedding_model_live.py for that.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.document_repository import DocumentRepository
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.chunk_embedding import EMBEDDING_DIMENSION, ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk

pytestmark = pytest.mark.integration


def _unit_vector(index: int) -> list[float]:
    """A 384-dim basis vector with a 1.0 at `index` and 0.0 elsewhere."""
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


def _near_unit_vector(index: int, *, lean_toward: int) -> list[float]:
    """Mostly `_unit_vector(index)`, tilted slightly toward another axis —
    close to it in cosine distance, but not identical."""
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 0.9
    vector[lean_toward] = 0.1
    return vector


def _opposite_unit_vector(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = -1.0
    return vector


async def _make_document(session: AsyncSession):
    repo = DocumentRepository(session)
    document = repo.new(
        filename=f"{uuid.uuid4()}.txt",
        original_filename="report.txt",
        content_type="text/plain",
        document_type=DocumentType.TXT,
        file_size=100,
        checksum=uuid.uuid4().hex + uuid.uuid4().hex,
        status=DocumentStatus.PROCESSED,
    )
    await session.flush()
    return document


async def _make_chunk(
    session: AsyncSession, document_id: uuid.UUID, *, index: int, content: str = "chunk"
) -> DocumentChunk:
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=document_id,
        chunk_index=index,
        content=content,
        character_count=len(content),
    )
    session.add(chunk)
    await session.flush()
    return chunk


def _make_embedding(
    chunk_id: uuid.UUID,
    vector: list[float],
    *,
    model: str = "test-model",
    model_version: str = "1",
) -> ChunkEmbedding:
    return ChunkEmbedding(
        id=uuid.uuid4(),
        document_chunk_id=chunk_id,
        embedding=vector,
        embedding_provider="local",
        embedding_model=model,
        embedding_model_version=model_version,
        embedding_dimension=EMBEDDING_DIMENSION,
    )


async def test_add_all_persists_embedding_with_vector(db_session: AsyncSession) -> None:
    document = await _make_document(db_session)
    chunk = await _make_chunk(db_session, document.id, index=0)
    repo = ChunkEmbeddingRepository(db_session)

    await repo.add_all([_make_embedding(chunk.id, _unit_vector(0))])

    ids = await repo.get_embedded_chunk_ids([chunk.id], model="test-model", model_version="1")
    assert ids == {chunk.id}


async def test_get_embedded_chunk_ids_filters_by_model_and_version(
    db_session: AsyncSession,
) -> None:
    document = await _make_document(db_session)
    chunk = await _make_chunk(db_session, document.id, index=0)
    repo = ChunkEmbeddingRepository(db_session)
    await repo.add_all([_make_embedding(chunk.id, _unit_vector(0), model="model-a")])

    same_model = await repo.get_embedded_chunk_ids([chunk.id], model="model-a", model_version="1")
    different_model = await repo.get_embedded_chunk_ids(
        [chunk.id], model="model-b", model_version="1"
    )

    assert same_model == {chunk.id}
    assert different_model == set()


async def test_count_for_document(db_session: AsyncSession) -> None:
    document = await _make_document(db_session)
    chunk_a = await _make_chunk(db_session, document.id, index=0)
    chunk_b = await _make_chunk(db_session, document.id, index=1)
    repo = ChunkEmbeddingRepository(db_session)
    await repo.add_all(
        [
            _make_embedding(chunk_a.id, _unit_vector(0)),
            _make_embedding(chunk_b.id, _unit_vector(1)),
        ]
    )

    assert await repo.count_for_document(document.id, model="test-model", model_version="1") == 2


async def test_duplicate_chunk_model_version_is_rejected(db_session: AsyncSession) -> None:
    document = await _make_document(db_session)
    chunk = await _make_chunk(db_session, document.id, index=0)
    repo = ChunkEmbeddingRepository(db_session)
    await repo.add_all([_make_embedding(chunk.id, _unit_vector(0))])

    with pytest.raises(IntegrityError):
        await repo.add_all([_make_embedding(chunk.id, _unit_vector(1))])


async def test_same_chunk_can_have_embeddings_from_two_different_models(
    db_session: AsyncSession,
) -> None:
    document = await _make_document(db_session)
    chunk = await _make_chunk(db_session, document.id, index=0)
    repo = ChunkEmbeddingRepository(db_session)

    await repo.add_all([_make_embedding(chunk.id, _unit_vector(0), model="model-a")])
    await repo.add_all([_make_embedding(chunk.id, _unit_vector(0), model="model-b")])

    assert await repo.count_for_document(document.id, model="model-a", model_version="1") == 1
    assert await repo.count_for_document(document.id, model="model-b", model_version="1") == 1


async def test_similarity_search_orders_by_cosine_distance_ascending(
    db_session: AsyncSession,
) -> None:
    document = await _make_document(db_session)
    identical_chunk = await _make_chunk(db_session, document.id, index=0, content="identical")
    similar_chunk = await _make_chunk(db_session, document.id, index=1, content="similar")
    orthogonal_chunk = await _make_chunk(db_session, document.id, index=2, content="orthogonal")
    opposite_chunk = await _make_chunk(db_session, document.id, index=3, content="opposite")

    repo = ChunkEmbeddingRepository(db_session)
    await repo.add_all(
        [
            _make_embedding(identical_chunk.id, _unit_vector(0)),
            _make_embedding(similar_chunk.id, _near_unit_vector(0, lean_toward=1)),
            _make_embedding(orthogonal_chunk.id, _unit_vector(1)),
            _make_embedding(opposite_chunk.id, _opposite_unit_vector(0)),
        ]
    )

    results = await repo.similarity_search(
        query_vector=_unit_vector(0), model="test-model", model_version="1", top_k=4
    )

    ordered_content = [chunk.content for _embedding, chunk, _distance in results]
    assert ordered_content == ["identical", "similar", "orthogonal", "opposite"]

    distances = [distance for *_rest, distance in results]
    assert distances[0] == pytest.approx(0.0, abs=1e-6)
    assert distances[-2] == pytest.approx(1.0, abs=1e-6)  # orthogonal
    assert distances[-1] == pytest.approx(2.0, abs=1e-6)  # opposite
    assert distances == sorted(distances)


async def test_similarity_search_only_matches_requested_model_and_version(
    db_session: AsyncSession,
) -> None:
    document = await _make_document(db_session)
    chunk = await _make_chunk(db_session, document.id, index=0, content="only chunk")
    repo = ChunkEmbeddingRepository(db_session)
    await repo.add_all([_make_embedding(chunk.id, _unit_vector(0), model="other-model")])

    results = await repo.similarity_search(
        query_vector=_unit_vector(0), model="test-model", model_version="1", top_k=5
    )

    assert results == []
