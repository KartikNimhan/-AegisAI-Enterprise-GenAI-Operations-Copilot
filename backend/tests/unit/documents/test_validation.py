"""Unit tests for upload-time file validation."""

from __future__ import annotations

import pytest

from app.documents.exceptions import (
    EmptyFileError,
    FileTooLargeError,
    InvalidContentTypeError,
    UnsafeFilenameError,
    UnsupportedDocumentTypeError,
)
from app.documents.validation import (
    determine_document_type,
    generate_storage_key,
    sanitize_filename,
    validate_content_type,
    validate_magic_bytes,
    validate_size,
)
from app.domain.enums.document_type import DocumentType

ALL_TYPES = ["pdf", "docx", "txt", "markdown"]


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("report.pdf", DocumentType.PDF),
        ("report.PDF", DocumentType.PDF),
        ("letter.docx", DocumentType.DOCX),
        ("notes.txt", DocumentType.TXT),
        ("readme.md", DocumentType.MARKDOWN),
        ("readme.markdown", DocumentType.MARKDOWN),
    ],
)
def test_determine_document_type_supported(filename: str, expected: DocumentType) -> None:
    assert determine_document_type(filename=filename, allowed_types=ALL_TYPES) == expected


def test_determine_document_type_rejects_unsupported_extension() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        determine_document_type(filename="virus.exe", allowed_types=ALL_TYPES)


def test_determine_document_type_rejects_missing_extension() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        determine_document_type(filename="noextension", allowed_types=ALL_TYPES)


def test_determine_document_type_respects_allowed_types_restriction() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        determine_document_type(filename="report.pdf", allowed_types=["docx", "txt", "markdown"])


@pytest.mark.parametrize(
    ("document_type", "content_type"),
    [
        (DocumentType.PDF, "application/pdf"),
        (
            DocumentType.DOCX,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (DocumentType.TXT, "text/plain"),
        (DocumentType.MARKDOWN, "text/markdown"),
        (DocumentType.MARKDOWN, "text/plain; charset=utf-8"),  # params stripped, plain accepted
    ],
)
def test_validate_content_type_accepts_expected(
    document_type: DocumentType, content_type: str
) -> None:
    validate_content_type(document_type=document_type, content_type=content_type)  # no raise


def test_validate_content_type_rejects_mismatch() -> None:
    with pytest.raises(InvalidContentTypeError):
        validate_content_type(document_type=DocumentType.PDF, content_type="image/png")


def test_validate_magic_bytes_accepts_valid_pdf_signature() -> None:
    validate_magic_bytes(document_type=DocumentType.PDF, content=b"%PDF-1.4\n...")


def test_validate_magic_bytes_rejects_mismatched_signature() -> None:
    with pytest.raises(InvalidContentTypeError):
        validate_magic_bytes(document_type=DocumentType.PDF, content=b"not a pdf at all")


def test_validate_magic_bytes_skips_check_for_formats_without_signature() -> None:
    validate_magic_bytes(document_type=DocumentType.TXT, content=b"anything at all")  # no raise


def test_validate_size_rejects_empty_file() -> None:
    with pytest.raises(EmptyFileError):
        validate_size(size=0, max_size=1000)


def test_validate_size_rejects_oversized_file() -> None:
    with pytest.raises(FileTooLargeError):
        validate_size(size=2000, max_size=1000)


def test_validate_size_accepts_within_bounds() -> None:
    validate_size(size=500, max_size=1000)  # no raise


def test_sanitize_filename_strips_path_traversal_components() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32\\evil.txt") == "evil.txt"


def test_sanitize_filename_keeps_a_plain_name_unchanged() -> None:
    assert sanitize_filename("report.pdf") == "report.pdf"


@pytest.mark.parametrize("filename", ["", ".", "..", "   "])
def test_sanitize_filename_rejects_unsafe_names(filename: str) -> None:
    with pytest.raises(UnsafeFilenameError):
        sanitize_filename(filename)


def test_generate_storage_key_uses_document_id_not_client_filename() -> None:
    import uuid

    document_id = uuid.uuid4()
    key = generate_storage_key(document_id=document_id, document_type=DocumentType.PDF)
    assert key == f"{document_id}.pdf"
