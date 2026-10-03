"""Unit tests for ContextAssembler: source boundaries, IDs, page metadata,
multi-document formatting, and character-budget truncation."""

from __future__ import annotations

import pytest

from app.rag.context.assembler import ContextAssembler

from .doubles import make_result


def test_assigns_sequential_source_ids_starting_at_one() -> None:
    results = [make_result(content="first"), make_result(content="second")]
    assembler = ContextAssembler(max_context_chars=10_000)

    assembled = assembler.assemble(results)

    assert [s.source_id for s in assembled.sources] == ["S1", "S2"]


def test_each_block_has_a_source_header_naming_the_document() -> None:
    result = make_result(
        content="Employees may claim travel expenses.", filename="Travel Policy.pdf"
    )
    assembler = ContextAssembler(max_context_chars=10_000)

    assembled = assembler.assemble([result])

    assert "[SOURCE 1]" in assembled.text
    assert "Document: Travel Policy.pdf" in assembled.text
    assert "Employees may claim travel expenses." in assembled.text


def test_page_number_is_included_when_known() -> None:
    result = make_result(page_number=7)
    assembler = ContextAssembler(max_context_chars=10_000)

    assembled = assembler.assemble([result])

    assert "Page: 7" in assembled.text
    assert assembled.sources[0].page_number == 7


def test_page_number_is_omitted_when_not_known() -> None:
    result = make_result(page_number=None)
    assembler = ContextAssembler(max_context_chars=10_000)

    assembled = assembler.assemble([result])

    assert "Page:" not in assembled.text


def test_multiple_documents_each_get_their_own_source_block() -> None:
    results = [
        make_result(content="from policy A", filename="A.pdf"),
        make_result(content="from policy B", filename="B.pdf"),
    ]
    assembler = ContextAssembler(max_context_chars=10_000)

    assembled = assembler.assemble(results)

    assert "Document: A.pdf" in assembled.text
    assert "Document: B.pdf" in assembled.text
    assert assembled.text.index("A.pdf") < assembled.text.index("B.pdf")


def test_not_truncated_when_everything_fits() -> None:
    results = [make_result(content="short")]
    assembler = ContextAssembler(max_context_chars=10_000)

    assembled = assembler.assemble(results)

    assert assembled.truncated is False
    assert len(assembled.sources) == 1


def test_truncates_when_results_exceed_the_character_budget() -> None:
    results = [make_result(content="x" * 100, filename=f"doc{i}.pdf") for i in range(5)]
    # Budget fits roughly one block, not all five.
    assembler = ContextAssembler(max_context_chars=150)

    assembled = assembler.assemble(results)

    assert assembled.truncated is True
    assert len(assembled.sources) < len(results)
    assert len(assembled.text) <= 150 or assembled.sources[0].source_id == "S1"


def test_always_includes_something_even_if_the_first_result_alone_exceeds_budget() -> None:
    results = [make_result(content="x" * 5000)]
    assembler = ContextAssembler(max_context_chars=100)

    assembled = assembler.assemble(results)

    assert assembled.truncated is True
    assert len(assembled.sources) == 1
    assert len(assembled.text) <= 100


def test_empty_results_produce_empty_context() -> None:
    assembler = ContextAssembler(max_context_chars=10_000)

    assembled = assembler.assemble([])

    assert assembled.text == ""
    assert assembled.sources == []
    assert assembled.truncated is False


def test_rejects_non_positive_max_context_chars() -> None:
    with pytest.raises(ValueError, match="max_context_chars"):
        ContextAssembler(max_context_chars=0)
