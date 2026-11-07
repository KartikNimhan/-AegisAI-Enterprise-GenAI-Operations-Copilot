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

import hashlib
import re
import uuid
from dataclasses import dataclass

from app.rag.retrieval.schemas import RetrievalResult

_BLOCK_SEPARATOR = "\n\n---\n\n"

# Names the rendering `model_visible_passage` applies (marker neutralization, then a cut to the
# recorded length). Saved with every citation (M10.4 decision 4): if the rendering ever changes,
# this must change too, so citations saved under the old rendering read as unavailable instead of
# showing text the model never saw.
PASSAGE_RENDERING_VERSION = "neutralize-markers-v1"


def passage_sha256(passage: str) -> str:
    """SHA-256 (64 lowercase hex characters) of a passage's UTF-8 bytes."""
    return hashlib.sha256(passage.encode("utf-8")).hexdigest()


# Text from a document that looks like one of OUR markers: `[SOURCE 2]`, `[/SOURCE 2]`, `[S3]`,
# `[S1, S2]`. Left alone, a document could plant a fake source boundary in the prompt, or write
# `[S3]` so that a model quoting it makes a citation the sanitizer would accept as valid. The
# sanitizer also accepts lenticular brackets (U+3010/U+3011) and a block label as a citation
# (`[SOURCE 1]`, alone or in a group such as `[S1, SOURCE 2]`, see app.rag.citations), so all of
# those count as look-alikes too.
_MARKER_LOOKALIKE = re.compile(
    r"[\[【]\s*/?\s*((?:SOURCE\s*\d+|S\d+)(?:\s*,\s*(?:SOURCE\s*\d+|S\d+))*)\s*[\]】]",
    re.IGNORECASE,
)


def neutralize_markers(text: str) -> str:
    """Rewrites marker look-alikes in untrusted text as `(S3)` / `(SOURCE 2)`: still readable, but
    no longer shaped like a source boundary or a citation. Only this exact shape is touched."""
    return _MARKER_LOOKALIKE.sub(lambda match: f"({match.group(1)})", text)


def _single_line(text: str) -> str:
    return " ".join(neutralize_markers(text).split())


def model_visible_passage(chunk_content: str, passage_chars: int) -> str:
    """The exact passage of a chunk that the model was given: its stored content with marker
    look-alikes neutralized, cut to the recorded length. Chunks are never edited after ingestion,
    so the stored content plus `AssembledSource.passage_chars` is enough to rebuild it later
    without keeping a copy of the text."""
    if passage_chars < 0:
        raise ValueError("passage_chars must not be negative")
    return neutralize_markers(chunk_content)[:passage_chars]


@dataclass(frozen=True)
class AssembledSource:
    """One chunk that made it into the assembled context, with the
    `source_id` the prompt and the LLM's citations both reference.

    `passage_chars` is how many characters of the chunk's neutralized content (see
    `model_visible_passage`) the model actually received, after the source header.
    `passage_truncated` is True when the context budget cut that passage short. Only the first
    source can be cut; a later source that does not fit is dropped and never appears here.
    `passage_sha256` is the SHA-256 of exactly that passage (rendered with
    `PASSAGE_RENDERING_VERSION`), so a later rebuild can be verified (M10.4 decision 4)."""

    source_id: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page_number: int | None
    distance: float
    similarity: float
    passage_chars: int
    passage_truncated: bool
    passage_sha256: str


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
            header_lines = [f"[SOURCE {index}]", f"Document: {_single_line(result.filename)}"]
            if result.page_number is not None:
                header_lines.append(f"Page: {result.page_number}")
            header = "\n".join(header_lines) + "\n\n"
            passage = neutralize_markers(result.content)
            block = header + passage

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
                    # The cut can fall inside the header, leaving none of the passage.
                    included = max(0, min(len(passage), available - len(header)))
                    sources.append(
                        _to_source(
                            source_id,
                            result,
                            passage=passage[:included],
                            passage_truncated=included < len(passage),
                        )
                    )
                    total_chars += len(block)
                truncated = True
                break

            blocks.append(block)
            sources.append(_to_source(source_id, result, passage=passage, passage_truncated=False))
            total_chars += separator_len + len(block)

        return AssembledContext(
            text=_BLOCK_SEPARATOR.join(blocks), sources=sources, truncated=truncated
        )


def _to_source(
    source_id: str, result: RetrievalResult, *, passage: str, passage_truncated: bool
) -> AssembledSource:
    """`passage` is exactly the text of this source the model received (after the header)."""
    return AssembledSource(
        source_id=source_id,
        chunk_id=result.chunk_id,
        document_id=result.document_id,
        filename=result.filename,
        chunk_index=result.chunk_index,
        page_number=result.page_number,
        distance=result.distance,
        similarity=result.similarity,
        passage_chars=len(passage),
        passage_truncated=passage_truncated,
        passage_sha256=passage_sha256(passage),
    )
