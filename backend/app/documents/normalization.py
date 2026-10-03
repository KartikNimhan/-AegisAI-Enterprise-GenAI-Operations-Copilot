"""Text normalization: the stage between extraction and chunking.

Deliberately conservative — this cleans up extraction/encoding noise, it
does not rewrite content. It never removes single line breaks (which may
be meaningful, e.g. in code blocks or poetry), never reflows paragraphs,
and never alters wording.
"""

from __future__ import annotations

import re
import unicodedata

_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)
# Any run of spaces/tabs (including a lone tab) becomes one space — tabs
# and spaces are both just "horizontal whitespace" for this purpose.
_HORIZONTAL_WHITESPACE_RUN = re.compile(r"[ \t]+")
_EXCESSIVE_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    if not text:
        return text

    # 1. Line endings: \r\n and bare \r both become \n.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Strip a leading BOM some decoders leave behind, and canonicalize
    #    unicode (NFC) — a non-destructive, well-defined operation that
    #    fixes many "looks like two characters, is actually one plus a
    #    combining mark" encoding artifacts without changing the text's
    #    meaning.
    normalized = normalized.removeprefix("﻿")
    normalized = unicodedata.normalize("NFC", normalized)

    # 3. Collapse horizontal whitespace (spaces/tabs) to one space, but
    #    only within a line — never touch the newlines themselves here.
    normalized = _HORIZONTAL_WHITESPACE_RUN.sub(" ", normalized)

    # 4. Strip trailing horizontal whitespace at the end of each line.
    normalized = _TRAILING_WHITESPACE.sub("", normalized)

    # 5. Collapse 3+ consecutive blank lines down to exactly one blank line
    #    (i.e. at most two consecutive \n), preserving paragraph boundaries
    #    without unbounded vertical gaps.
    normalized = _EXCESSIVE_BLANK_LINES.sub("\n\n", normalized)

    return normalized.strip()
