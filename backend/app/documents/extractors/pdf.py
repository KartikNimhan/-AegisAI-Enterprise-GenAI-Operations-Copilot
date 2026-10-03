"""PDF text extraction via pypdf.

Extracts page by page (not one flat blob) specifically so page numbers can
be carried through to chunk metadata later — see `app.documents.chunking`.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.documents.exceptions import ExtractionError
from app.documents.extractors.base import DocumentExtractor, ExtractionResult


class PdfExtractor(DocumentExtractor):
    def extract(self, content: bytes) -> ExtractionResult:
        try:
            reader = PdfReader(BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            doc_info = reader.metadata
        except PyPdfError as exc:
            raise ExtractionError(f"Could not read PDF: {exc}") from exc

        metadata: dict[str, Any] = {"page_count": len(pages)}
        if doc_info is not None and doc_info.title:
            metadata["title"] = doc_info.title

        # Always at least one page so downstream chunking can treat every
        # format uniformly, even for a (degenerate) zero-page PDF.
        return ExtractionResult(pages=pages or [""], metadata=metadata)
