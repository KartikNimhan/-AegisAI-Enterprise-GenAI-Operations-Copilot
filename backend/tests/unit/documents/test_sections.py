"""M10.9: section headings for chunks (Markdown and DOCX), added to chunk metadata only."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from typing import Any

import pytest
from docx import Document as DocxDocument

from app.config import Settings
from app.documents.chunking.base import ChunkData
from app.documents.chunking.recursive import RecursiveChunker
from app.documents.extractors.docx import MAX_HEADING_LENGTH, DocxExtractor
from app.documents.normalization import normalize_text
from app.documents.sections import (
    MAX_SECTION_LENGTH,
    assign_sections,
    markdown_headings,
    positioned_headings,
)
from app.services.document_service import DocumentService

from ..services.document_doubles import (
    FakeDocumentChunkRepository,
    FakeDocumentRepository,
    FakeSession,
    FakeStorage,
)


def _titles(text: str) -> list[str]:
    return [title for _offset, title in markdown_headings(text)]


# -- Markdown headings ---------------------------------------------------------------


def test_atx_and_setext_headings_are_found_in_order() -> None:
    text = (
        "# Travel\n\nIntro.\n\n## Hotels ##\n\nText.\n\nMeals\n=====\n\nMore.\n\nTaxis\n---\nEnd."
    )
    assert _titles(text) == ["Travel", "Hotels", "Meals", "Taxis"]


def test_heading_offsets_point_at_the_heading_line() -> None:
    text = "Intro.\n\n# First\n\nBody.\n\nSecond\n======\n"
    for offset, title in markdown_headings(text):
        assert text[offset:].startswith("# First" if title == "First" else "Second")


def test_lines_inside_fenced_code_are_not_headings() -> None:
    text = (
        "# Real\n\n```\n# not a heading\nText\n---\n```\n\n~~~~\n## also not\n~~~~\n\n## Also real"
    )
    assert _titles(text) == ["Real", "Also real"]


def test_things_that_only_look_like_headings_are_ignored() -> None:
    text = "#hashtag without a space\n\n- a list item\n---\n\n> a quote\n===\n\n#   \n\nText"
    assert _titles(text) == []


def test_a_long_heading_is_bounded() -> None:
    assert _titles("# " + "x" * 1000) == ["x" * MAX_SECTION_LENGTH]


# -- assigning sections to chunks -----------------------------------------------------


def _chunk(index: int, content: str, **metadata: object) -> ChunkData:
    return ChunkData(
        chunk_index=index, content=content, character_count=len(content), metadata=dict(metadata)
    )


def test_each_chunk_gets_the_heading_in_effect_where_its_own_text_starts() -> None:
    text = "Preface text.\n\n# One\n\nAlpha text.\n\n# Two\n\nBeta text."
    chunks = [
        _chunk(0, "Preface text."),
        _chunk(1, "# One\n\nAlpha text."),
        _chunk(2, "Alpha text.\n\n# Two"),
        _chunk(3, "Beta text."),
    ]

    result = assign_sections(text, chunks, markdown_headings(text))

    # Chunk 2 repeats "Alpha text." from chunk 1; its own text is "# Two".
    assert [c.metadata.get("section") for c in result] == [None, "One", "Two", "Two"]
    assert [(c.chunk_index, c.content, c.character_count) for c in result] == [
        (c.chunk_index, c.content, c.character_count) for c in chunks
    ]


def test_other_metadata_is_kept_and_an_unlocatable_chunk_gets_no_guess() -> None:
    text = "# Head\n\nBody."
    chunks = [_chunk(0, "Body.", page_number=1), _chunk(1, "text that is not there")]
    result = assign_sections(text, chunks, markdown_headings(text))
    assert result[0].metadata == {"page_number": 1, "section": "Head"}
    assert result[1].metadata == {}


def test_repeated_chunk_text_is_located_in_order() -> None:
    text = "# A\n\nSame.\n\n# B\n\nSame."
    result = assign_sections(
        text, [_chunk(0, "Same."), _chunk(1, "Same.")], markdown_headings(text)
    )
    assert [c.metadata["section"] for c in result] == ["A", "B"]


def test_positioned_headings_find_the_line_by_position_and_verify_it() -> None:
    text = "Summary\nThe summary text.\n\nDetails\nMore."
    assert positioned_headings(text, [(0, "Summary"), (2, "Details")]) == [
        (0, "Summary"),
        (27, "Details"),
    ]
    # A wrong position or a prefix that is not the start of that line is skipped, never guessed.
    assert positioned_headings(text, [(1, "Details"), (9, "Summary"), (-1, "More.")]) == []


# -- DOCX extraction (M10 review finding L7: by position, not by text) ---------------------------


def _docx(build: Callable[[Any], None] | None = None) -> bytes:
    document = DocxDocument()
    if build is None:
        document.add_heading("Expense policy", level=0)  # the "Title" style
        document.add_paragraph("Introduction paragraph.")
        document.add_heading("Meals", level=1)
        document.add_paragraph("Meals are reimbursed up to 60 euros.")
        document.add_heading("  ", level=2)  # empty headings are skipped
        document.add_heading("Mileage", level=2)
        document.add_paragraph("Mileage is paid per kilometre.")
    else:
        build(document)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _sections_of(content: bytes) -> list[str | None]:
    result = DocxExtractor().extract(content)
    text = normalize_text(result.pages[0])
    chunks = [
        _chunk(i, line) for i, line in enumerate(line for line in text.split("\n") if line.strip())
    ]
    labelled = assign_sections(text, chunks, positioned_headings(text, result.headings))
    return [c.metadata.get("section") for c in labelled]


def test_the_docx_extractor_reports_heading_positions_outside_the_document_metadata() -> None:
    result = DocxExtractor().extract(_docx())
    assert result.headings == ((0, "Expense policy"), (2, "Meals"), (4, "Mileage"))
    assert "headings" not in result.metadata


def test_body_text_identical_to_a_heading_does_not_take_its_place() -> None:
    def build(document: Any) -> None:
        document.add_paragraph("Meals")  # body text, before the real heading
        document.add_paragraph("Introduction.")
        document.add_heading("Meals", level=1)
        document.add_paragraph("Meals are reimbursed.")
        document.add_paragraph("Meals")  # body text again, after it

    # Lines: "Meals" (body), "Introduction.", "Meals" (heading), "Meals are …", "Meals" (body)
    assert _sections_of(_docx(build)) == [None, None, "Meals", "Meals", "Meals"]


def test_a_long_heading_is_found_and_its_section_bounded() -> None:
    long_title = "Policy " + "x" * 900

    def build(document: Any) -> None:
        document.add_heading(long_title, level=1)
        document.add_paragraph("Body.")

    result = DocxExtractor().extract(_docx(build))
    ((ordinal, prefix),) = result.headings
    assert ordinal == 0 and len(prefix) == MAX_HEADING_LENGTH
    assert _sections_of(_docx(build)) == [long_title[:MAX_SECTION_LENGTH]] * 2


def test_a_paragraph_with_a_line_break_counts_its_lines() -> None:
    def build(document: Any) -> None:
        paragraph = document.add_paragraph("First line")
        paragraph.add_run().add_break()
        paragraph.add_run("second line")
        document.add_heading("After", level=1)
        document.add_paragraph("Body.")

    assert DocxExtractor().extract(_docx(build)).headings == ((2, "After"),)
    assert _sections_of(_docx(build)) == [None, None, "After", "After"]


def test_a_failing_style_lookup_skips_that_heading_but_keeps_the_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import docx.text.paragraph

    content = _docx()  # built before the patch: building sets styles
    original = docx.text.paragraph.Paragraph.style

    def flaky_style(self: Any) -> Any:
        if self.text == "Meals":
            raise KeyError("missing style definition")
        return original.fget(self)  # type: ignore[union-attr]

    monkeypatch.setattr(docx.text.paragraph.Paragraph, "style", property(flaky_style))

    result = DocxExtractor().extract(content)

    assert "Introduction paragraph." in result.pages[0]  # extraction still succeeded
    assert result.headings == ((0, "Expense policy"), (4, "Mileage"))


# -- end to end through DocumentService ------------------------------------------------


def _service() -> tuple[DocumentService, FakeDocumentChunkRepository]:
    chunks = FakeDocumentChunkRepository()
    service = DocumentService(
        session=FakeSession(),  # type: ignore[arg-type]
        settings=Settings(document_chunk_size=60, document_chunk_overlap=10),
        documents=FakeDocumentRepository(),  # type: ignore[arg-type]
        chunks=chunks,  # type: ignore[arg-type]
        storage=FakeStorage(),
    )
    return service, chunks


MARKDOWN = (
    b"Opening words before any heading.\n\n# Travel\n\nEconomy fares for short flights only.\n\n"
    b"## Hotels\n\nHotel stays are reimbursed up to the nightly cap.\n"
)


async def test_markdown_chunks_carry_sections_and_are_otherwise_unchanged() -> None:
    service, stored = _service()
    await service.upload(filename="policy.md", content_type="text/markdown", content=MARKDOWN)

    expected = RecursiveChunker().chunk(
        pages=[normalize_text(MARKDOWN.decode())], chunk_size=60, chunk_overlap=10
    )
    assert [(c.chunk_index, c.content) for c in stored.chunks] == [
        (c.chunk_index, c.content) for c in expected
    ]
    sections = [(c.metadata_ or {}).get("section") for c in stored.chunks]
    assert sections[0] is None
    assert "Travel" in sections and "Hotels" in sections
    assert sections[-1] == "Hotels"


async def test_docx_chunks_carry_sections_from_heading_styles() -> None:
    service, stored = _service()
    await service.upload(
        filename="policy.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=_docx(),
    )
    # Chunks of 60 with an overlap of 10: each chunk is labelled by where its own text begins.
    assert [(c.metadata_ or {}).get("section") for c in stored.chunks] == [
        "Expense policy",
        "Meals",
        "Mileage",
    ]


async def test_plain_text_gets_no_section_even_with_markdown_like_lines() -> None:
    service, stored = _service()
    await service.upload(
        filename="notes.txt",
        content_type="text/plain",
        content=b"# Not a heading here\n\nPlain text body.",
    )
    assert all("section" not in (c.metadata_ or {}) for c in stored.chunks)
