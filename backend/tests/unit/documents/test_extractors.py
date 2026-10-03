"""Unit tests for text extractors. No real files on disk — small in-memory
fixtures from tests/document_fixtures.py."""

from __future__ import annotations

import pytest

from app.documents.exceptions import ExtractionError
from app.documents.extractors.docx import DocxExtractor
from app.documents.extractors.markdown import MarkdownExtractor
from app.documents.extractors.pdf import PdfExtractor
from app.documents.extractors.text import PlainTextExtractor

from ...document_fixtures import (
    make_corrupt_pdf_bytes,
    make_docx_bytes,
    make_empty_docx_bytes,
    make_markdown_bytes,
    make_pdf_bytes,
    make_txt_bytes,
)


def test_pdf_extractor_extracts_text_and_page_count() -> None:
    result = PdfExtractor().extract(make_pdf_bytes(text="Hello PDF World"))

    assert "Hello PDF World" in result.text
    assert result.metadata["page_count"] == 1
    assert not result.is_empty


def test_pdf_extractor_raises_extraction_error_for_corrupt_pdf() -> None:
    with pytest.raises(ExtractionError):
        PdfExtractor().extract(make_corrupt_pdf_bytes())


def test_docx_extractor_extracts_paragraphs() -> None:
    result = DocxExtractor().extract(make_docx_bytes())

    assert "Hello DOCX World." in result.text
    assert "This is a second paragraph for testing extraction." in result.text
    assert result.metadata["paragraph_count"] == 4
    assert result.metadata["non_empty_paragraph_count"] == 3


def test_docx_extractor_handles_empty_document_without_pretending_success() -> None:
    result = DocxExtractor().extract(make_empty_docx_bytes())

    assert result.is_empty


def test_docx_extractor_raises_extraction_error_for_garbage_bytes() -> None:
    with pytest.raises(ExtractionError):
        DocxExtractor().extract(b"this is not a docx file")


def test_text_extractor_decodes_utf8() -> None:
    result = PlainTextExtractor().extract(make_txt_bytes())

    assert "Hello World." in result.text
    assert result.metadata["encoding"] == "utf-8"


def test_text_extractor_detects_bom() -> None:
    result = PlainTextExtractor().extract(b"\xef\xbb\xbfHello with BOM")

    assert result.text == "Hello with BOM"
    assert result.metadata["encoding"] == "utf-8-sig"


def test_text_extractor_falls_back_for_non_utf8_bytes() -> None:
    # 0xe9 alone is not valid UTF-8 but is valid cp1252/latin-1 ("é").
    result = PlainTextExtractor().extract(b"caf\xe9")

    assert "caf" in result.text
    assert result.metadata["encoding"] in {"cp1252", "latin-1"}


def test_text_extractor_on_empty_bytes_is_empty() -> None:
    result = PlainTextExtractor().extract(b"")

    assert result.is_empty


def test_markdown_extractor_extracts_raw_markdown_source() -> None:
    result = MarkdownExtractor().extract(make_markdown_bytes())

    assert "# Sample Markdown" in result.text
    assert "- item one" in result.text
