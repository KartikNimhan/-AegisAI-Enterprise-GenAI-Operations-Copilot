"""Reading saved citations (M10.4 T5/T6).

A citation row says which source an answer used; it never says the caller may read that source
TODAY. Every read therefore:

1. finds the citation only through the caller's own conversation (`CitationRepository`, scoped
   by `conversation_filter`): anything else is "not found" (404), exactly like a message;
2. looks the cited chunk up through `DocumentChunkRepository`, which applies the CURRENT document
   read filter and requires the chunk to still belong to the same document;
3. rebuilds the passage the model saw (`model_visible_passage`) and checks the saved rendering
   version and SHA-256 (M10.4 decision 4).

If step 2 or 3 fails, the source is UNAVAILABLE. Deleted, made private, never readable by this
caller, re-chunked, or a passage mismatch all produce the same answer, with no file name, page or
text (decision 3), so the response reveals nothing about which case applies. The reason is logged
(content-free) for operators only (decision 8). Support is never claimed: `support` is always
"not_verified" (decision 11).
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

import structlog
from fastapi import Depends

from app.core.exceptions import NotFoundError
from app.core.security import AccessScopeDep
from app.db.repositories.citation_repository import CitationRepository
from app.db.repositories.document_chunk_repository import DocumentChunkRepository
from app.dependencies import DBSessionDep
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.message_citation import MessageCitation
from app.rag.context.assembler import (
    PASSAGE_RENDERING_VERSION,
    neutralize_markers,
    passage_sha256,
)

logger = structlog.get_logger(__name__)

MAX_NEIGHBORS = 2  # M10.4 decision 6: at most two chunks on each side, off by default

UnavailableReason = Literal[
    "source_not_readable", "document_mismatch", "rendering_changed", "passage_mismatch"
]


@dataclass(frozen=True)
class NeighborChunk:
    chunk_id: uuid.UUID
    chunk_index: int
    page: int | None
    section: str | None
    text: str


@dataclass(frozen=True)
class CitationView:
    """A citation as the caller may see it now. Every source-describing field is None unless
    `available` is True."""

    message_id: uuid.UUID
    source_id: str
    position: int
    cited: bool
    passage_truncated: bool
    available: bool
    document_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    filename: str | None = None
    chunk_index: int | None = None
    page: int | None = None
    section: str | None = None
    similarity: float | None = None
    passage: str | None = None
    neighbors_before: tuple[NeighborChunk, ...] = ()
    neighbors_after: tuple[NeighborChunk, ...] = ()


def _page(chunk: DocumentChunk) -> int | None:
    value = (chunk.metadata_ or {}).get("page_number")
    return value if isinstance(value, int) else None


def _section(chunk: DocumentChunk) -> str | None:
    value = (chunk.metadata_ or {}).get("section")
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True)
class _Passage:
    text: str


def rebuild_passage(
    citation: MessageCitation, chunk: DocumentChunk
) -> _Passage | UnavailableReason:
    """The exact passage the model saw, or why it can no longer be shown."""
    if citation.rendering_version != PASSAGE_RENDERING_VERSION:
        return "rendering_changed"
    rendered = neutralize_markers(chunk.content)
    if citation.passage_chars > len(rendered):
        return "passage_mismatch"
    passage = rendered[: citation.passage_chars]
    if passage_sha256(passage) != citation.passage_sha256:
        return "passage_mismatch"
    return _Passage(passage)


class CitationService:
    def __init__(self, *, citations: CitationRepository, chunks: DocumentChunkRepository) -> None:
        self._citations = citations
        self._chunks = chunks

    def _resolve(
        self, citation: MessageCitation, found: tuple[DocumentChunk, Document] | None
    ) -> CitationView:
        base = {
            "message_id": citation.message_id,
            "source_id": citation.source_id,
            "position": citation.position,
            "cited": citation.cited,
            "passage_truncated": citation.passage_truncated,
        }
        reason: UnavailableReason
        if found is None:
            reason = "source_not_readable"
        elif found[0].document_id != citation.document_id or found[1].id != citation.document_id:
            # The chunk lookup is keyed by chunk id; the citation recorded a document too, and
            # both must agree (M10 review finding L1). Same answer as any other unavailable source.
            reason = "document_mismatch"
        else:
            chunk, document = found
            rebuilt = rebuild_passage(citation, chunk)
            if isinstance(rebuilt, _Passage):
                return CitationView(
                    **base,
                    available=True,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    filename=document.original_filename,
                    chunk_index=chunk.chunk_index,
                    page=_page(chunk),
                    section=_section(chunk),
                    similarity=citation.similarity,
                    passage=rebuilt.text,
                )
            reason = rebuilt
        logger.info(
            "citation_unavailable",
            message_id=str(citation.message_id),
            source_id=citation.source_id,
            reason=reason,
        )
        return CitationView(**base, available=False)

    async def get(
        self,
        *,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        source_id: str,
        neighbors: int = 0,
    ) -> CitationView:
        if not 0 <= neighbors <= MAX_NEIGHBORS:
            raise ValueError(f"neighbors must be between 0 and {MAX_NEIGHBORS}")
        citation = await self._citations.get(
            conversation_id=conversation_id, message_id=message_id, source_id=source_id
        )
        if citation is None:
            raise NotFoundError("Citation not found")
        readable = await self._chunks.get_readable_with_documents(
            [(citation.chunk_id, citation.document_id)]
        )
        view = self._resolve(citation, readable.get(citation.chunk_id))
        if not view.available or neighbors == 0 or view.chunk_index is None:
            return view
        # Neighbours come from the SAME document only, through the same current read filter.
        nearby = await self._chunks.list_readable_range(
            citation.document_id,
            first_index=view.chunk_index - neighbors,
            last_index=view.chunk_index + neighbors,
        )

        def as_neighbor(chunk: DocumentChunk) -> NeighborChunk:
            # Rendered exactly like the cited passage: marker look-alikes (`[S3]`,
            # `[SOURCE 2]`, ...) are neutralized, so surrounding text can never pose as a
            # citation (M10 review finding L3). Neighbours are context, not the passage the model
            # saw, so no hash applies; they still come only from the same, currently readable
            # document.
            return NeighborChunk(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                page=_page(chunk),
                section=_section(chunk),
                text=neutralize_markers(chunk.content),
            )

        cited_index = view.chunk_index
        return dataclasses.replace(
            view,
            neighbors_before=tuple(as_neighbor(c) for c in nearby if c.chunk_index < cited_index),
            neighbors_after=tuple(as_neighbor(c) for c in nearby if c.chunk_index > cited_index),
        )

    async def for_conversation(
        self, conversation_id: uuid.UUID
    ) -> dict[uuid.UUID, list[CitationView]]:
        """Every message's citations in the caller's own conversation, resolved against the
        caller's CURRENT access, keyed by message id. Two queries in total, whatever the length
        of the conversation. Messages without saved citations (older than M10.4, or answers
        with no sources) are simply absent: the caller shows `citations: []`."""
        citations = await self._citations.list_for_conversation(conversation_id)
        if not citations:
            return {}
        readable = await self._chunks.get_readable_with_documents(
            [(c.chunk_id, c.document_id) for c in citations]
        )
        resolved: dict[uuid.UUID, list[CitationView]] = {}
        for citation in citations:
            resolved.setdefault(citation.message_id, []).append(
                self._resolve(citation, readable.get(citation.chunk_id))
            )
        return resolved


def get_citation_service(session: DBSessionDep, scope: AccessScopeDep) -> CitationService:
    return CitationService(
        citations=CitationRepository(session, scope), chunks=DocumentChunkRepository(session, scope)
    )


CitationServiceDep = Annotated[CitationService, Depends(get_citation_service)]
