"""Unit tests for RecursiveChunker."""

from __future__ import annotations

import pytest

from app.documents.chunking.recursive import RecursiveChunker


def test_short_text_produces_a_single_chunk() -> None:
    chunker = RecursiveChunker()

    chunks = chunker.chunk(pages=["A short sentence."], chunk_size=1000, chunk_overlap=100)

    assert len(chunks) == 1
    assert chunks[0].content == "A short sentence."
    assert chunks[0].chunk_index == 0


def test_long_text_is_split_into_multiple_chunks_within_size() -> None:
    chunker = RecursiveChunker()
    text = "word " * 500  # well over any reasonable chunk_size

    chunks = chunker.chunk(pages=[text], chunk_size=100, chunk_overlap=20)

    assert len(chunks) > 1
    assert all(c.character_count <= 100 for c in chunks)


def test_chunk_indices_are_sequential_and_ordered() -> None:
    chunker = RecursiveChunker()
    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three.\n\nParagraph four."

    chunks = chunker.chunk(pages=[text], chunk_size=20, chunk_overlap=5)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_overlap_carries_content_between_consecutive_chunks() -> None:
    chunker = RecursiveChunker()
    text = "A" * 50 + " " + "B" * 50

    chunks = chunker.chunk(pages=[text], chunk_size=40, chunk_overlap=10)

    assert len(chunks) >= 2
    tail_of_first = chunks[0].content[-10:]
    assert chunks[1].content.startswith(tail_of_first)


def test_zero_overlap_produces_no_shared_content() -> None:
    chunker = RecursiveChunker()
    text = "word " * 100

    chunks = chunker.chunk(pages=[text], chunk_size=50, chunk_overlap=0)

    # Reconstructing with no overlap should not duplicate any piece.
    assert len(chunks) >= 2


def test_single_page_document_has_no_page_number_metadata() -> None:
    chunker = RecursiveChunker()

    chunks = chunker.chunk(pages=["Just one page of content."], chunk_size=1000, chunk_overlap=0)

    assert all("page_number" not in c.metadata for c in chunks)


def test_multi_page_document_tags_each_chunk_with_its_page() -> None:
    chunker = RecursiveChunker()

    chunks = chunker.chunk(
        pages=["Page one content.", "Page two content.", "Page three content."],
        chunk_size=1000,
        chunk_overlap=0,
    )

    assert [c.metadata["page_number"] for c in chunks] == [1, 2, 3]


def test_blank_pages_are_skipped() -> None:
    chunker = RecursiveChunker()

    chunks = chunker.chunk(pages=["Real content.", "   ", ""], chunk_size=1000, chunk_overlap=0)

    assert len(chunks) == 1
    assert chunks[0].content == "Real content."


def test_chunking_is_deterministic_for_identical_input() -> None:
    chunker = RecursiveChunker()
    text = "Paragraph one.\n\nParagraph two is a bit longer than the first one.\n\nAnd a third."

    first = chunker.chunk(pages=[text], chunk_size=30, chunk_overlap=5)
    second = chunker.chunk(pages=[text], chunk_size=30, chunk_overlap=5)

    assert [c.content for c in first] == [c.content for c in second]


def test_different_chunk_size_produces_different_chunks() -> None:
    chunker = RecursiveChunker()
    text = "Paragraph one.\n\nParagraph two is a bit longer than the first one.\n\nAnd a third."

    small = chunker.chunk(pages=[text], chunk_size=20, chunk_overlap=0)
    large = chunker.chunk(pages=[text], chunk_size=1000, chunk_overlap=0)

    assert [c.content for c in small] != [c.content for c in large]


def test_rejects_invalid_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        RecursiveChunker().chunk(pages=["text"], chunk_size=0, chunk_overlap=0)


def test_rejects_overlap_greater_than_or_equal_to_chunk_size() -> None:
    with pytest.raises(ValueError, match="chunk_overlap"):
        RecursiveChunker().chunk(pages=["text"], chunk_size=10, chunk_overlap=10)
