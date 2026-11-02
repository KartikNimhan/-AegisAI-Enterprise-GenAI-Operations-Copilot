"""Extraction ceilings: a small file must not expand into unbounded work (synthetic data only)."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.config import Settings
from app.documents.exceptions import ExtractionError
from app.documents.extractors import (
    ExtractionLimits,
    ExtractionResult,
    enforce_extracted_size,
    get_extractor,
)
from app.documents.extractors.docx import DocxExtractor, check_zip_bounds
from app.documents.extractors.pdf import PdfExtractor
from app.domain.enums.document_type import DocumentType


def make_docx(text: str = "hello") -> bytes:
    import docx

    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_pdf(pages: int) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_zip(entries: int, payload: bytes = b"x") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for i in range(entries):
            archive.writestr(f"p{i}.xml", payload)
    return buffer.getvalue()


def test_normal_docx_and_pdf_pass_default_limits() -> None:
    assert "hello" in DocxExtractor().extract(make_docx()).text
    assert PdfExtractor().extract(make_pdf(3)) is not None


def test_docx_expansion_over_limit_is_rejected_before_decompression() -> None:
    bomb = make_zip(1, b"A" * 2_000_000)
    assert len(bomb) < 20_000  # tiny file, large expansion
    with pytest.raises(ExtractionError, match="expands to"):
        check_zip_bounds(bomb, ExtractionLimits(max_uncompressed_bytes=1_000_000))


def test_docx_entry_count_over_limit_is_rejected() -> None:
    with pytest.raises(ExtractionError, match="parts"):
        check_zip_bounds(make_zip(20), ExtractionLimits(max_zip_entries=10))


def test_docx_extractor_applies_limits() -> None:
    with pytest.raises(ExtractionError, match="expands to"):
        DocxExtractor(ExtractionLimits(max_uncompressed_bytes=100)).extract(make_docx())


def test_not_a_zip_is_an_extraction_error() -> None:
    with pytest.raises(ExtractionError):
        check_zip_bounds(b"not a zip", ExtractionLimits())


def test_pdf_page_cap() -> None:
    with pytest.raises(ExtractionError, match="pages"):
        PdfExtractor(ExtractionLimits(max_pdf_pages=2)).extract(make_pdf(3))
    PdfExtractor(ExtractionLimits(max_pdf_pages=3)).extract(make_pdf(3))


def test_extracted_chars_cap_applies_to_any_format() -> None:
    result = ExtractionResult(pages=["x" * 50])
    enforce_extracted_size(result, ExtractionLimits(max_extracted_chars=50))
    with pytest.raises(ExtractionError, match="characters"):
        enforce_extracted_size(result, ExtractionLimits(max_extracted_chars=49))


def test_get_extractor_with_limits_is_configured() -> None:
    limits = ExtractionLimits(max_pdf_pages=1)
    assert get_extractor(DocumentType.PDF, limits)._limits == limits  # type: ignore[attr-defined]
    assert get_extractor(DocumentType.DOCX, limits)._limits == limits  # type: ignore[attr-defined]
    assert get_extractor(DocumentType.TXT, limits) is get_extractor(DocumentType.TXT)


def test_limits_from_settings_and_validation() -> None:
    settings = Settings(_env_file=None, debug=False, document_max_pdf_pages=7)  # type: ignore[call-arg]
    assert ExtractionLimits.from_settings(settings).max_pdf_pages == 7
    for bad in (
        {"document_max_pdf_pages": 0},
        {"document_max_uncompressed_bytes": 10},
        {"document_max_extracted_chars": 5},
    ):
        with pytest.raises(ValueError):
            Settings(_env_file=None, debug=False, **bad)  # type: ignore[call-arg]
