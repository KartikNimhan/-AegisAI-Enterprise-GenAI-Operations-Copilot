"""Upload-time file validation.

Defense in depth, deliberately layered — no single check is trusted alone:
1. extension (cheap, but spoofable)
2. declared content-type (also client-supplied, also spoofable)
3. magic bytes sniffed from the actual content, where a format has a
   reliable signature (PDF, DOCX)
4. size bounds

The client-supplied filename is never used to build a filesystem path —
`generate_storage_key` derives an internal key from the document's own id.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from app.documents.exceptions import (
    EmptyFileError,
    FileTooLargeError,
    InvalidContentTypeError,
    UnsafeFilenameError,
    UnsupportedDocumentTypeError,
)
from app.domain.enums.document_type import DocumentType

EXTENSION_TO_TYPE: dict[str, DocumentType] = {
    ".pdf": DocumentType.PDF,
    ".docx": DocumentType.DOCX,
    ".txt": DocumentType.TXT,
    ".md": DocumentType.MARKDOWN,
    ".markdown": DocumentType.MARKDOWN,
}

TYPE_TO_EXTENSION: dict[DocumentType, str] = {
    DocumentType.PDF: ".pdf",
    DocumentType.DOCX: ".docx",
    DocumentType.TXT: ".txt",
    DocumentType.MARKDOWN: ".md",
}

# Client-declared content-types accepted per type. Deliberately permissive
# for text/markdown, since browsers and HTTP clients disagree widely on
# what MIME type to send for them (text/plain is common for both).
ACCEPTED_CONTENT_TYPES: dict[DocumentType, frozenset[str]] = {
    DocumentType.PDF: frozenset({"application/pdf"}),
    DocumentType.DOCX: frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ),
    DocumentType.TXT: frozenset({"text/plain"}),
    DocumentType.MARKDOWN: frozenset({"text/markdown", "text/x-markdown", "text/plain"}),
}

# Magic-byte signatures for formats that reliably have one. TXT/Markdown
# have no such signature — they're validated by successfully decoding as
# text instead (see app.documents.extractors.text).
MAGIC_BYTES: dict[DocumentType, bytes] = {
    DocumentType.PDF: b"%PDF-",
    DocumentType.DOCX: b"PK\x03\x04",
}


def sanitize_filename(filename: str) -> str:
    """Returns a bare basename, stripping any path components the client
    might have sent — this is for safe display/storage in the database
    only; it is never used to build a filesystem path (see `app.storage`).
    """
    # PurePosixPath handles both "/" and a client sending literal
    # backslashes in a filename without misinterpreting them as separators
    # on the server's own OS (important since this runs on Windows too).
    name = PurePosixPath(filename.replace("\\", "/")).name
    stripped = "".join(ch for ch in name if ch.isprintable()).strip()
    if not stripped or stripped in {".", ".."}:
        raise UnsafeFilenameError("Filename is missing or unsafe")
    return stripped


def determine_document_type(*, filename: str, allowed_types: list[str]) -> DocumentType:
    suffix = PurePosixPath(filename.lower()).suffix
    document_type = EXTENSION_TO_TYPE.get(suffix)
    if document_type is None:
        raise UnsupportedDocumentTypeError(f"Unsupported file extension: {suffix or '(none)'!r}")
    if document_type.value not in allowed_types:
        raise UnsupportedDocumentTypeError(
            f"Document type {document_type.value!r} is not currently accepted"
        )
    return document_type


def validate_content_type(*, document_type: DocumentType, content_type: str) -> None:
    accepted = ACCEPTED_CONTENT_TYPES[document_type]
    # Strip parameters like "; charset=utf-8" before comparing.
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized not in accepted:
        raise InvalidContentTypeError(
            f"Content-Type {content_type!r} does not match expected type for "
            f"{document_type.value!r}"
        )


def validate_magic_bytes(*, document_type: DocumentType, content: bytes) -> None:
    signature = MAGIC_BYTES.get(document_type)
    if signature is None:
        return  # TXT/Markdown: no reliable signature to check.
    if not content.startswith(signature):
        raise InvalidContentTypeError(
            f"File content does not match the expected format for {document_type.value!r}"
        )


def validate_size(*, size: int, max_size: int) -> None:
    if size <= 0:
        raise EmptyFileError("Uploaded file is empty")
    if size > max_size:
        raise FileTooLargeError(f"File size {size} bytes exceeds the maximum of {max_size} bytes")


def generate_storage_key(*, document_id: uuid.UUID, document_type: DocumentType) -> str:
    return f"{document_id}{TYPE_TO_EXTENSION[document_type]}"
