"""Inline-citation validation.

The prompt asks the model to cite sources as `[S1]`, `[S2, S3]`. A model can still cite an id that
was never in its context (`[S9]`), which would point a reader at evidence that does not exist. The
retrieved source ids are the only valid ones, so every citation marker is checked against them:
valid ids are kept, invalid ids are removed (a group left empty disappears entirely), and the ids
that were removed are reported so the caller can log/return them.

Only text that is *shaped like* a citation (`[S<digits>]`, optionally comma-separated) is touched;
any other bracketed text is left exactly as written.

`StreamingCitationSanitizer` applies the same rule to a token stream. A marker can be split across
chunks (`"[S"`, `"9]"`), so text from an opening `[` is held back until the marker is either
complete (checked, then emitted or dropped) or can no longer be a citation (emitted unchanged).
The hold is bounded, so a stray `[` cannot stall the stream. Text already sent cannot be taken
back, so unlike the non-streaming path the stream does not close the space before punctuation
that a removed marker leaves behind.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_GROUP = re.compile(r"\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]")
_ID = re.compile(r"S\d+")
# Characters that can appear between "[" and "]" in a citation marker.
_MARKER_CHARS = frozenset("S0123456789, \t")
# Longest marker we will wait for: far more than any realistic "[S1, S2, ... ]" group.
_MAX_MARKER_LENGTH = 64


@dataclass(frozen=True)
class CitationReport:
    """What sanitizing did: ids cited (valid, in first-seen order) and ids removed (invalid)."""

    cited: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(frozen=True)
class SanitizedText:
    text: str
    report: CitationReport


def _resolve(match: re.Match[str], allowed: frozenset[str]) -> tuple[str, list[str], list[str]]:
    ids = _ID.findall(match.group(1))
    valid = [i for i in dict.fromkeys(ids) if i in allowed]
    invalid = [i for i in dict.fromkeys(ids) if i not in allowed]
    replacement = f"[{', '.join(valid)}]" if valid else ""
    return replacement, valid, invalid


def sanitize_citations(text: str, allowed_ids: Iterable[str]) -> SanitizedText:
    allowed = frozenset(allowed_ids)
    cited: list[str] = []
    removed: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        replacement, valid, invalid = _resolve(match, allowed)
        cited.extend(valid)
        removed.extend(invalid)
        return replacement

    cleaned = _GROUP.sub(_sub, text)
    return SanitizedText(
        text=_tidy(cleaned) if removed else cleaned,
        report=CitationReport(
            cited=tuple(dict.fromkeys(cited)), removed=tuple(dict.fromkeys(removed))
        ),
    )


def _tidy(text: str) -> str:
    """Remove the stray space a deleted marker leaves before punctuation (`"fact [S9]."`)."""
    return re.sub(r" +([.,;:!?])", r"\1", text)


class StreamingCitationSanitizer:
    def __init__(self, allowed_ids: Iterable[str]) -> None:
        self._allowed = frozenset(allowed_ids)
        self._held = ""
        self._cited: list[str] = []
        self._removed: list[str] = []

    @property
    def report(self) -> CitationReport:
        return CitationReport(
            cited=tuple(dict.fromkeys(self._cited)), removed=tuple(dict.fromkeys(self._removed))
        )

    def feed(self, delta: str) -> str:
        """Returns the text that is safe to emit now (possibly empty while a marker is pending)."""
        out: list[str] = []
        for char in delta:
            if self._held:
                if char == "]":
                    out.append(self._close(self._held + char))
                    self._held = ""
                    continue
                if char in _MARKER_CHARS and len(self._held) < _MAX_MARKER_LENGTH:
                    self._held += char
                    continue
                # Not a citation after all: release what was held, then handle this char normally.
                out.append(self._held)
                self._held = ""
            if char == "[":
                self._held = "["
            else:
                out.append(char)
        return "".join(out)

    def finish(self) -> str:
        """Releases anything still held (an unterminated marker is not a citation)."""
        held, self._held = self._held, ""
        return held

    def _close(self, candidate: str) -> str:
        match = _GROUP.fullmatch(candidate)
        if match is None:
            return candidate
        replacement, valid, invalid = _resolve(match, self._allowed)
        self._cited.extend(valid)
        self._removed.extend(invalid)
        return replacement
