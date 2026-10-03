"""The provider-neutral interface every chunking strategy must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChunkData:
    """One chunk, not yet a persisted `DocumentChunk` — `DocumentService`
    assigns the deterministic id (see `app.documents.chunk_ids`) and
    attaches `document_id` when building the ORM row."""

    chunk_index: int
    content: str
    character_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


class Chunker(ABC):
    """Splits normalized text into ordered chunks.

    `pages` always has at least one element (see `ExtractionResult`) — for
    formats without real pagination, callers pass a single page containing
    the whole document, and implementations must not assume page 1 is
    special.
    """

    @abstractmethod
    def chunk(self, *, pages: list[str], chunk_size: int, chunk_overlap: int) -> list[ChunkData]:
        raise NotImplementedError
