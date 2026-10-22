"""DOCX text extraction via python-docx.

DOCX has no native "pages" concept (pagination is a rendering-time layout
detail, not stored in the file) — treated as a single page, consistent
with `ExtractionResult`'s "at least one page" contract.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Any

from docx import Document as DocxDocument

from app.documents.exceptions import ExtractionError
from app.documents.extractors.base import DocumentExtractor, ExtractionLimits, ExtractionResult


def check_zip_bounds(content: bytes, limits: ExtractionLimits) -> None:
    """Reads only the zip directory (no decompression) and rejects a container that would expand
    past the limits. The declared sizes are trustworthy as a ceiling: `zipfile` never yields more
    than the declared size of an entry."""
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"Could not read DOCX: {exc}") from exc
    if len(entries) > limits.max_zip_entries:
        raise ExtractionError(
            f"The DOCX contains {len(entries)} parts, over the limit of {limits.max_zip_entries}"
        )
    expanded = sum(entry.file_size for entry in entries)
    if expanded > limits.max_uncompressed_bytes:
        raise ExtractionError(
            f"The DOCX expands to {expanded} bytes, over the limit of "
            f"{limits.max_uncompressed_bytes}"
        )


class DocxExtractor(DocumentExtractor):
    def __init__(self, limits: ExtractionLimits | None = None) -> None:
        self._limits = limits or ExtractionLimits()

    def extract(self, content: bytes) -> ExtractionResult:
        check_zip_bounds(content, self._limits)
        try:
            document = DocxDocument(BytesIO(content))
            paragraphs = [p.text for p in document.paragraphs]
        except Exception as exc:
            # A malformed DOCX can fail in python-docx itself (e.g.
            # PackageNotFoundError) or in the zip/XML layers underneath it
            # (BadZipFile, ParseError, KeyError for a missing part) — none
            # of those should surface as an unhandled 500 from the API.
            raise ExtractionError(f"Could not read DOCX: {exc}") from exc

        text = "\n".join(paragraphs)
        metadata: dict[str, Any] = {
            "paragraph_count": len(paragraphs),
            "non_empty_paragraph_count": sum(1 for p in paragraphs if p.strip()),
        }
        return ExtractionResult(pages=[text], metadata=metadata)
