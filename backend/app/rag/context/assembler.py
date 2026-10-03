"""Turns ranked retrieval results into a structured context block plus a
stable source mapping.

Independent of how results were retrieved (vector search, a future hybrid
strategy) — it only ever sees `RetrievalResult`s. Never concatenates raw
chunk text without a source boundary: each chunk gets a `[SOURCE n]`
header naming the document (and page, when known) before its content, so
the LLM — and a human reading the prompt in logs/debugging — can always
tell where a given piece of text came from.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.rag.retrieval.schemas import RetrievalResult

_BLOCK_SEPARATOR = "\n\n---\n\n"


@dataclass(frozen=True)
class AssembledSource:
    """One chunk that made it into the assembled context, with the
    `source_id` the prompt and the LLM's citations both reference."""

    source_id: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page_number: int | None
    distance: float
    similarity: float


@dataclass(frozen=True)
class AssembledContext:
    text: str
    sources: list[AssembledSource]
    truncated: bool


class ContextAssembler:
    def __init__(self, *, max_context_chars: int) -> None:
        if max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive")
        self._max_context_chars = max_context_chars

    def assemble(self, results: list[RetrievalResult]) -> AssembledContext:
        blocks: list[str] = []
        sources: list[AssembledSource] = []
        total_chars = 0
        truncated = False

        for index, result in enumerate(results, start=1):
            source_id = f"S{index}"
            header_lines = [f"[SOURCE {index}]", f"Document: {result.filename}"]
            if result.page_number is not None:
                header_lines.append(f"Page: {result.page_number}")
            block = "\n".join(header_lines) + "\n\n" + result.content

            separator_len = len(_BLOCK_SEPARATOR) if blocks else 0
            if total_chars + separator_len + len(block) > self._max_context_chars:
                if not blocks:
                    # Always include at least something from the single
                    # most relevant result, rather than returning an empty
                    # context because the very first chunk alone exceeds
                    # the budget.
                    available = self._max_context_chars
                    block = block[:available]
                    blocks.append(block)
                    sources.append(_to_source(source_id, result))
                    total_chars += len(block)
                truncated = True
                break

            blocks.append(block)
            sources.append(_to_source(source_id, result))
            total_chars += separator_len + len(block)

        return AssembledContext(
            text=_BLOCK_SEPARATOR.join(blocks), sources=sources, truncated=truncated
        )


def _to_source(source_id: str, result: RetrievalResult) -> AssembledSource:
    return AssembledSource(
        source_id=source_id,
        chunk_id=result.chunk_id,
        document_id=result.document_id,
        filename=result.filename,
        chunk_index=result.chunk_index,
        page_number=result.page_number,
        distance=result.distance,
        similarity=result.similarity,
    )
