"""Markdown extraction.

Markdown is extracted as plain text (not rendered to HTML/parsed into a
structural tree) — chunking operates on the raw Markdown source, which
already carries useful structure (headings, lists) as plain text. A
separate class from `PlainTextExtractor` so each `DocumentType` has its own
registry entry and can diverge later (e.g. stripping front-matter) without
affecting `.txt` handling.
"""

from __future__ import annotations

from app.documents.extractors.base import DocumentExtractor, ExtractionResult
from app.documents.extractors.text import decode_text_bytes


class MarkdownExtractor(DocumentExtractor):
    def extract(self, content: bytes) -> ExtractionResult:
        text, encoding = decode_text_bytes(content)
        return ExtractionResult(pages=[text], metadata={"encoding": encoding})
