"""Unit tests for deterministic chunk identifiers."""

from __future__ import annotations

import uuid

from app.documents.chunk_ids import compute_chunk_id

DOC_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
DOC_B = uuid.UUID("22222222-2222-4222-8222-222222222222")


def test_same_inputs_produce_the_same_id() -> None:
    first = compute_chunk_id(document_id=DOC_A, chunk_size=1000, chunk_overlap=150, chunk_index=0)
    second = compute_chunk_id(document_id=DOC_A, chunk_size=1000, chunk_overlap=150, chunk_index=0)

    assert first == second


def test_different_documents_produce_different_ids() -> None:
    """Two owners who upload byte-identical files get two documents; their chunks must
    not collide on the chunk primary key."""
    first = compute_chunk_id(document_id=DOC_A, chunk_size=1000, chunk_overlap=150, chunk_index=0)
    second = compute_chunk_id(document_id=DOC_B, chunk_size=1000, chunk_overlap=150, chunk_index=0)

    assert first != second


def test_different_chunking_config_produces_a_different_id() -> None:
    base = compute_chunk_id(document_id=DOC_A, chunk_size=1000, chunk_overlap=150, chunk_index=0)
    different_size = compute_chunk_id(
        document_id=DOC_A, chunk_size=500, chunk_overlap=150, chunk_index=0
    )
    different_overlap = compute_chunk_id(
        document_id=DOC_A, chunk_size=1000, chunk_overlap=50, chunk_index=0
    )

    assert base != different_size
    assert base != different_overlap


def test_different_chunk_index_produces_a_different_id() -> None:
    first = compute_chunk_id(document_id=DOC_A, chunk_size=1000, chunk_overlap=150, chunk_index=0)
    second = compute_chunk_id(document_id=DOC_A, chunk_size=1000, chunk_overlap=150, chunk_index=1)

    assert first != second


def test_id_is_a_valid_uuid5() -> None:
    result = compute_chunk_id(document_id=DOC_A, chunk_size=1000, chunk_overlap=150, chunk_index=0)

    assert isinstance(result, uuid.UUID)
    assert result.version == 5
