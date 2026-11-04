"""Turning an answer's assembled sources into citation records to save (M10.4 T4).

A record is a REFERENCE (ids, lengths, a hash), never document text (M10.4 decision 2). It is
saved in the same transaction as the assistant message it belongs to, so a rolled-back answer
leaves no citations behind.

Similarity (owner decision, 2026-11-03, Option A): the database only accepts [-1.0, 1.0]. A
non-finite score (NaN, +infinity, -infinity) means something upstream is broken; it is REJECTED
with `CitationIntegrityError`, never turned into a plausible-looking number. A finite score is
clamped into the range, because pgvector's floating-point rounding can put an exact match a hair
above 1.0.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from app.rag.context.assembler import PASSAGE_RENDERING_VERSION, AssembledSource

_SOURCE_ID = re.compile(r"S([1-9][0-9]{0,2})")


class CitationIntegrityError(ValueError):
    """A citation record would break an invariant (non-finite score, malformed source id)."""


@dataclass(frozen=True)
class CitationRecord:
    source_id: str
    position: int
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    similarity: float
    cited: bool
    passage_chars: int
    passage_truncated: bool
    rendering_version: str
    passage_sha256: str


def persistable_similarity(value: float) -> float:
    if not math.isfinite(value):
        raise CitationIntegrityError(f"similarity must be finite, got {value!r}")
    return min(1.0, max(-1.0, float(value)))


def _position(source_id: str) -> int:
    match = _SOURCE_ID.fullmatch(source_id)
    if match is None:
        raise CitationIntegrityError(f"malformed source id {source_id!r}")
    return int(match.group(1))


def build_citation_records(
    sources: Sequence[AssembledSource], cited_ids: Collection[str]
) -> list[CitationRecord]:
    """One record per assembled source, in context order, marked cited when the validated
    answer text cites it."""
    return [
        CitationRecord(
            source_id=source.source_id,
            position=_position(source.source_id),
            document_id=source.document_id,
            chunk_id=source.chunk_id,
            similarity=persistable_similarity(source.similarity),
            cited=source.source_id in cited_ids,
            passage_chars=source.passage_chars,
            passage_truncated=source.passage_truncated,
            rendering_version=PASSAGE_RENDERING_VERSION,
            passage_sha256=source.passage_sha256,
        )
        for source in sources
    ]
