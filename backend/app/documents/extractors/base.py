"""The provider-neutral interface every text extractor must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.documents.exceptions import ExtractionError

if TYPE_CHECKING:
    from app.config import Settings


@dataclass(frozen=True)
class ExtractionLimits:
    """Ceilings that keep a small, hostile file from becoming a huge amount of work.

    The 20 MB upload limit bounds the file, not what it expands to: a few hundred KB of DOCX can
    hold gigabytes of XML, and a PDF can have hundreds of thousands of pages. Exceeding a limit
    fails the document with a clear message (status FAILED); nothing is silently truncated.
    """

    max_uncompressed_bytes: int = 64 * 1024 * 1024  # DOCX (a zip): total expanded size
    max_zip_entries: int = 10_000  # DOCX: number of parts
    max_pdf_pages: int = 2_000
    max_extracted_chars: int = 20_000_000  # any format: size of the extracted text

    @classmethod
    def from_settings(cls, settings: Settings) -> ExtractionLimits:
        return cls(
            max_uncompressed_bytes=settings.document_max_uncompressed_bytes,
            max_pdf_pages=settings.document_max_pdf_pages,
            max_extracted_chars=settings.document_max_extracted_chars,
        )


@dataclass(frozen=True)
class ExtractionResult:
    """Normalized extraction output.

    `pages` is always at least one element: formats without real pagination
    (DOCX, TXT, Markdown) use a single "page" containing the whole document,
    so `app.documents.chunking` can treat every format uniformly. `text` is
    the convenience-joined form (pages separated by a blank line).
    """

    pages: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def enforce_extracted_size(result: ExtractionResult, limits: ExtractionLimits) -> None:
    """Rejects an extraction whose text is larger than the limit (every format)."""
    size = sum(len(page) for page in result.pages)
    if size > limits.max_extracted_chars:
        raise ExtractionError(
            f"The document contains {size} characters of text, over the limit of "
            f"{limits.max_extracted_chars}"
        )


class DocumentExtractor(ABC):
    """Extracts text from raw file bytes. Never invents content: if nothing
    can be extracted, returns an `ExtractionResult` with empty/blank pages
    rather than raising — `DocumentService` decides what an empty result
    means for document status, since "no text found" is a legitimate
    (if unusable) outcome, not necessarily a bug in the extractor.
    """

    @abstractmethod
    def extract(self, content: bytes) -> ExtractionResult:
        raise NotImplementedError
