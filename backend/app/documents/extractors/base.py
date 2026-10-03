"""The provider-neutral interface every text extractor must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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
