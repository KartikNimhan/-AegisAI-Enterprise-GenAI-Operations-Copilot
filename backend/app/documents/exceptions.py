"""Typed exceptions for document ingestion.

`DocumentValidationError` (and subclasses) are raised for problems with the
upload itself, before anything is stored — these map to HTTP 400 (see
`core/exceptions.py`). Problems discovered *during* processing (extraction,
chunking) are deliberately NOT raised past `DocumentService` — they're
caught there and recorded as a `FAILED` document status instead, since the
upload itself already succeeded. See
docs/architecture/decisions/005-document-ingestion.md.
"""

from __future__ import annotations


class DocumentValidationError(Exception):
    """Base class for upload-time validation failures (maps to HTTP 400)."""


class UnsupportedDocumentTypeError(DocumentValidationError):
    pass


class InvalidContentTypeError(DocumentValidationError):
    pass


class FileTooLargeError(DocumentValidationError):
    pass


class EmptyFileError(DocumentValidationError):
    pass


class UnsafeFilenameError(DocumentValidationError):
    pass


class ExtractionError(Exception):
    """Raised by an extractor when it cannot produce text at all.

    Caught by `DocumentService`, which records it as a `FAILED` document —
    never propagated to the API layer as an HTTP error, since the document
    row (and uploaded file) already exist by this point.
    """
