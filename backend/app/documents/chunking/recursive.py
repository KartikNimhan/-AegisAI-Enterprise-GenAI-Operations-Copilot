"""Recursive, structure-aware chunking.

Each page is chunked independently — a chunk never spans two pages. For
multi-page PDFs this means every chunk has an exact, unambiguous page
reference (rather than a possibly-ambiguous page range), which matters more
for traceability than saving the handful of chunks that would otherwise
straddle a page boundary. Single-page documents (DOCX/TXT/Markdown) are
unaffected — "page" isn't a meaningful concept for them, so no cross-page
behavior is ever exercised.

Algorithm (no external framework): split on the first separator in
`_SEPARATORS`; any piece still over `chunk_size` is recursively split on
the next separator, down to a hard character-window fallback; the
resulting small pieces are then greedily merged back up to `chunk_size`,
carrying `chunk_overlap` characters from the end of one merged chunk into
the start of the next. Purely deterministic — no randomness, no model
calls — so the same input always produces the same chunks.
"""

from __future__ import annotations

from app.documents.chunking.base import ChunkData, Chunker

# Tried in order: paragraph breaks, line breaks, sentence-ish breaks, word
# breaks, then "" (a hard per-character fallback with no separator at all).
_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


class RecursiveChunker(Chunker):
    def chunk(self, *, pages: list[str], chunk_size: int, chunk_overlap: int) -> list[ChunkData]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and < chunk_size")

        chunks: list[ChunkData] = []
        chunk_index = 0
        multi_page = len(pages) > 1

        for page_number, page_text in enumerate(pages, start=1):
            if not page_text.strip():
                continue
            pieces = _split(page_text, chunk_size, _SEPARATORS)
            for merged in _merge(pieces, chunk_size, chunk_overlap):
                content = merged.strip()
                if not content:
                    continue
                metadata = {"page_number": page_number} if multi_page else {}
                chunks.append(
                    ChunkData(
                        chunk_index=chunk_index,
                        content=content,
                        character_count=len(content),
                        metadata=metadata,
                    )
                )
                chunk_index += 1

        return chunks


def _split(text: str, chunk_size: int, separators: tuple[str, ...]) -> list[str]:
    """Splits `text` into pieces no longer than `chunk_size`, preferring
    the earliest separator in `separators` that achieves this. Pieces
    concatenate back to exactly `text` (separators are kept, not discarded)
    so no content or whitespace is silently lost before merging."""
    if len(text) <= chunk_size:
        return [text]
    if not separators:
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    separator, *rest = separators
    if separator:
        raw = text.split(separator)
        pieces = [p + separator for p in raw[:-1]] + [raw[-1]]
    else:
        pieces = list(text)

    result: list[str] = []
    for piece in pieces:
        if len(piece) > chunk_size:
            result.extend(_split(piece, chunk_size, tuple(rest)))
        else:
            result.append(piece)
    return result


def _merge(pieces: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """Greedily recombines small pieces into chunks as close to
    `chunk_size` as possible without exceeding it, carrying the last
    `chunk_overlap` characters of each chunk into the start of the next."""
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > chunk_size:
            chunks.append(current)
            current = (current[-chunk_overlap:] if chunk_overlap else "") + piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks
