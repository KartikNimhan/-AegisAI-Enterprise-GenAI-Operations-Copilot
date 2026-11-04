"""Section headings for chunks (M10.9).

A chunk's `metadata["section"]` is the heading in effect where the chunk's own text begins (after
the overlap it repeats from the previous chunk): the nearest heading at or before that point. It
is computed after chunking and never changes a chunk's content, index or id, so it is purely
additive. Only formats whose headings can be read reliably get one:

- Markdown: ATX headings (`# Title` … `###### Title`) and setext headings (a line underlined with
  `===` or `---`), ignoring anything inside fenced code blocks;
- DOCX: paragraphs styled "Title" or "Heading N", reported by the extractor in
  `ExtractionResult.headings`.

PDF and plain text get no section: they carry no dependable heading structure. Documents
ingested before M10.9 keep their chunks as they are (no reprocessing or backfill); their chunks
simply have no section.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import replace

from app.documents.chunking.base import ChunkData
from app.documents.normalization import normalize_text

MAX_SECTION_LENGTH = 200

_ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_OR_QUOTE = re.compile(r"^ {0,3}([-*+>]|\d+[.)])\s")


def _clean(title: str) -> str | None:
    title = " ".join(title.split())
    if not title:
        return None
    return title[:MAX_SECTION_LENGTH]


def markdown_headings(text: str) -> list[tuple[int, str]]:
    """(offset of the heading line, heading text) for each Markdown heading, in order."""
    headings: list[tuple[int, str]] = []
    fence: str | None = None
    offset = 0
    previous: tuple[int, str] | None = None  # the last plain paragraph line (setext candidate)
    for line in text.split("\n"):
        start = offset
        offset += len(line) + 1
        fence_match = _FENCE.match(line)
        if fence is not None:
            if (
                fence_match
                and fence_match.group(1)[0] == fence[0]
                and len(fence_match.group(1)) >= len(fence)
            ):
                fence = None
            previous = None
            continue
        if fence_match:
            fence = fence_match.group(1)
            previous = None
            continue
        atx = _ATX.match(line)
        if atx:
            title = _clean(atx.group(2))
            if title:
                headings.append((start, title))
            previous = None
            continue
        if _SETEXT.match(line) and previous is not None:
            title = _clean(previous[1])
            if title:
                headings.append((previous[0], title))
            previous = None
            continue
        stripped = line.strip()
        previous = (start, stripped) if stripped and not _LIST_OR_QUOTE.match(line) else None
    return headings


_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def is_blank_line(line: str) -> bool:
    """Blank as normalization sees it: nothing but spaces and tabs (`normalize_text` strips those
    from line ends and collapses runs of blank lines, but never removes a line with content)."""
    return line.strip(" \t") == ""


def non_blank_lines(text: str) -> list[str]:
    return [line for line in _LINE_BREAK.split(text) if not is_blank_line(line)]


def positioned_headings(text: str, headings: Iterable[tuple[int, str]]) -> list[tuple[int, str]]:
    """(offset, title) for headings given by POSITION (M10 review finding L7): each is
    `(ordinal, prefix)`, the heading's first line being the `ordinal`-th non-blank line of the
    extracted text (counted from 0) and `prefix` the start of that line.

    Normalization keeps every line with content, so the ordinal finds the same line in the
    normalized `text`. (One exception: a leading line holding only a BOM or non-ASCII whitespace,
    which the final strip removes, shifts every ordinal by one.) A heading is used only if that
    line really starts with the normalized prefix; otherwise it is skipped, never guessed.
    Matching by position (not by text) means a body paragraph with the same words as a heading
    can never take its place.
    """
    lines: list[tuple[int, str]] = []
    offset = 0
    for line in text.split("\n"):
        if not is_blank_line(line):
            lines.append((offset, line))
        offset += len(line) + 1
    found: list[tuple[int, str]] = []
    for ordinal, prefix in headings:
        if not 0 <= ordinal < len(lines):
            continue
        line_offset, line = lines[ordinal]
        expected = normalize_text(prefix)
        if not expected or not line.strip().startswith(expected):
            continue
        title = _clean(line)
        if title and (not found or found[-1][0] < line_offset):
            found.append((line_offset, title))
    return found


def assign_sections(
    text: str, chunks: Sequence[ChunkData], headings: Sequence[tuple[int, str]]
) -> list[ChunkData]:
    """Returns the chunks with `metadata["section"]` set to the heading in effect where each
    chunk's OWN text begins, where one exists. Content, index and every other metadata key are
    unchanged.

    A chunk's own text begins after the overlap it repeats from the previous chunk (and any
    whitespace), so a chunk that carries the end of one section into the start of the next is
    labelled with the next. Each chunk is located by searching `text` for its content after the
    previous chunk's start (chunks are in order); a chunk that cannot be located gets no section
    rather than a guessed one.
    """
    offsets = [offset for offset, _title in headings]
    result: list[ChunkData] = []
    cursor = 0
    previous_end = 0
    for chunk in chunks:
        position = text.find(chunk.content, cursor)
        if position < 0:
            result.append(chunk)
            continue
        end = position + len(chunk.content)
        own_start = max(position, previous_end)
        while own_start < end and text[own_start].isspace():
            own_start += 1
        if own_start >= end:  # nothing new in this chunk: judge it by where it starts
            own_start = position
        cursor = position + 1  # the next chunk starts later (chunks advance even with overlap)
        previous_end = end
        index = bisect_right(offsets, own_start) - 1  # the last heading at or before it
        if index < 0:
            result.append(chunk)
        else:
            section = headings[index][1]
            result.append(replace(chunk, metadata={**chunk.metadata, "section": section}))
    return result
