"""Response schemas for saved citations (M10.4 T5/T6).

Two shapes, chosen by `status`:
- `available`: the source is readable by the caller NOW and the rebuilt passage matched the saved
  hash; it carries the passage text and source metadata.
- `unavailable`: anything else (deleted, made private, never readable, mismatch). It has NO
  fields that describe the source (no file name, page, ids or text), so nothing can leak by
  accident (M10.4 decision 3).

`support` is always "not_verified": retrieval alone never shows that a source supports a claim
(M10 decision 6, ADR 017 D-5).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.services.citation_service import CitationView, NeighborChunk

SupportStatus = Literal["not_verified"]


class CitationPassage(BaseModel):
    text: str = Field(description="Exactly the passage of the chunk the model was given.")
    characters: int
    truncated: bool = Field(description="The context budget cut this passage short.")


class CitationNeighbor(BaseModel):
    chunk_id: uuid.UUID
    chunk_index: int
    page: int | None = None
    section: str | None = None
    text: str

    @classmethod
    def from_neighbor(cls, neighbor: NeighborChunk) -> CitationNeighbor:
        return cls(
            chunk_id=neighbor.chunk_id,
            chunk_index=neighbor.chunk_index,
            page=neighbor.page,
            section=neighbor.section,
            text=neighbor.text,
        )


class CitationNeighbors(BaseModel):
    before: list[CitationNeighbor]
    after: list[CitationNeighbor]


class AvailableCitation(BaseModel):
    status: Literal["available"] = "available"
    message_id: uuid.UUID
    source_id: str
    cited: bool
    support: SupportStatus = "not_verified"
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    filename: str
    chunk_index: int
    page: int | None = None
    section: str | None = None
    similarity: float
    passage: CitationPassage
    neighbors: CitationNeighbors | None = Field(
        default=None, description="Present only when neighbors were requested."
    )


class UnavailableCitation(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    message_id: uuid.UUID
    source_id: str
    cited: bool
    support: SupportStatus = "not_verified"


CitationResponse = Annotated[AvailableCitation | UnavailableCitation, Field(discriminator="status")]


def citation_response(
    view: CitationView, *, neighbors_requested: bool
) -> AvailableCitation | UnavailableCitation:
    if not view.available:
        return UnavailableCitation(
            message_id=view.message_id, source_id=view.source_id, cited=view.cited
        )
    assert view.passage is not None and view.document_id is not None and view.chunk_id is not None
    assert view.filename is not None and view.chunk_index is not None
    assert view.similarity is not None
    return AvailableCitation(
        message_id=view.message_id,
        source_id=view.source_id,
        cited=view.cited,
        document_id=view.document_id,
        chunk_id=view.chunk_id,
        filename=view.filename,
        chunk_index=view.chunk_index,
        page=view.page,
        section=view.section,
        similarity=view.similarity,
        passage=CitationPassage(
            text=view.passage, characters=len(view.passage), truncated=view.passage_truncated
        ),
        neighbors=(
            CitationNeighbors(
                before=[CitationNeighbor.from_neighbor(n) for n in view.neighbors_before],
                after=[CitationNeighbor.from_neighbor(n) for n in view.neighbors_after],
            )
            if neighbors_requested
            else None
        ),
    )


class MessageCitationSummary(BaseModel):
    """A citation as listed with a reopened conversation (no passage text; the citation endpoint
    returns that). Every field that describes the source, `passage_truncated` included, is null
    unless `status` is "available": an unavailable source reveals nothing about itself, exactly
    like `UnavailableCitation` (M10 review finding L2)."""

    source_id: str
    status: Literal["available", "unavailable"]
    cited: bool
    passage_truncated: bool | None = None
    support: SupportStatus = "not_verified"
    document_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    filename: str | None = None
    chunk_index: int | None = None
    page: int | None = None
    section: str | None = None

    @classmethod
    def from_view(cls, view: CitationView) -> MessageCitationSummary:
        if not view.available:
            return cls(source_id=view.source_id, status="unavailable", cited=view.cited)
        return cls(
            source_id=view.source_id,
            status="available",
            cited=view.cited,
            passage_truncated=view.passage_truncated,
            document_id=view.document_id,
            chunk_id=view.chunk_id,
            filename=view.filename,
            chunk_index=view.chunk_index,
            page=view.page,
            section=view.section,
        )
