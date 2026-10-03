"""DOCX text extraction via python-docx.

DOCX has no native "pages" concept (pagination is a rendering-time layout
detail, not stored in the file) — treated as a single page, consistent
with `ExtractionResult`'s "at least one page" contract.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document as DocxDocument

from app.documents.exceptions import ExtractionError
from app.documents.extractors.base import DocumentExtractor, ExtractionResult


class DocxExtractor(DocumentExtractor):
    def extract(self, content: bytes) -> ExtractionResult:
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
