"""Builds the structured `Document.metadata_` blob.

Deliberately small and bounded: extractor-specific facts (encoding, DOCX
paragraph count, PDF title) plus a couple of normalization stats — never
the extracted text itself or anything unbounded in size.
"""

from __future__ import annotations

from typing import Any


def build_document_metadata(
    *,
    extraction_metadata: dict[str, Any],
    original_character_count: int,
    normalized_character_count: int,
) -> dict[str, Any]:
    return {
        **extraction_metadata,
        "normalization": {
            "original_character_count": original_character_count,
            "normalized_character_count": normalized_character_count,
        },
    }
