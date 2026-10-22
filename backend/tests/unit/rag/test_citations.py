"""Inline-citation validation: valid ids kept, invalid ids removed, odd brackets left alone,
and the streaming sanitizer gives the same answer however the text is split into chunks."""

from __future__ import annotations

import pytest

from app.rag.citations import StreamingCitationSanitizer, sanitize_citations

ALLOWED = ["S1", "S2"]


def test_valid_citations_are_unchanged() -> None:
    result = sanitize_citations("Claim A [S1] and claim B [S2].", ALLOWED)

    assert result.text == "Claim A [S1] and claim B [S2]."
    assert result.report.cited == ("S1", "S2")
    assert result.report.removed == ()


def test_unknown_citation_is_removed_and_reported() -> None:
    result = sanitize_citations("The limit is 50 [S9].", ALLOWED)

    assert result.text == "The limit is 50."
    assert result.report.removed == ("S9",)
    assert result.report.cited == ()


def test_a_group_keeps_only_its_valid_ids() -> None:
    result = sanitize_citations("Both apply [S1, S7, S2].", ALLOWED)

    assert result.text == "Both apply [S1, S2]."
    assert result.report.cited == ("S1", "S2")
    assert result.report.removed == ("S7",)


def test_no_sources_means_every_citation_is_invalid() -> None:
    result = sanitize_citations("Made up [S1].", [])

    assert result.text == "Made up."
    assert result.report.removed == ("S1",)


def test_text_that_only_looks_bracketed_is_not_touched() -> None:
    text = "See [1], [Appendix S9], [S], [s1], [S1x] and array[S9x]."

    result = sanitize_citations(text, ALLOWED)

    assert result.text == text
    assert result.report == sanitize_citations("", ALLOWED).report


def test_leading_zero_ids_do_not_alias_a_valid_source() -> None:
    result = sanitize_citations("Alias [S01].", ALLOWED)

    assert result.text == "Alias."
    assert result.report.removed == ("S01",)


def test_duplicates_are_reported_once() -> None:
    result = sanitize_citations("[S1] [S1] [S5] [S5]", ALLOWED)

    assert result.report.cited == ("S1",)
    assert result.report.removed == ("S5",)


# -- Streaming ------------------------------------------------------------------


def _stream(
    parts: list[str], allowed: list[str] = ALLOWED
) -> tuple[str, StreamingCitationSanitizer]:
    sanitizer = StreamingCitationSanitizer(allowed)
    out = "".join(sanitizer.feed(part) for part in parts) + sanitizer.finish()
    return out, sanitizer


def test_streaming_marker_split_across_chunks_is_validated() -> None:
    out, sanitizer = _stream(["Fact ", "[S", "9", "] and ", "[", "S1", "]."])

    assert out == "Fact  and [S1]."
    assert sanitizer.report.removed == ("S9",)
    assert sanitizer.report.cited == ("S1",)


@pytest.mark.parametrize(
    "text",
    [
        "Claim [S1] then [S9], and [S1, S4] plus [x] and [S1.",
        "[[S1]] [S2",
        "no brackets at all",
        "tail [",
        "[S9][S1][S9]",
    ],
)
def test_streaming_equals_non_streaming_for_every_split(text: str) -> None:
    expected = sanitize_citations(text, ALLOWED)

    # one character at a time, and the whole text at once
    for parts in ([c for c in text], [text]):
        out, sanitizer = _stream(parts)
        # whitespace around a removed marker differs by design (see the module docs)
        assert "".join(out.split()) == "".join(expected.text.split())
        assert sanitizer.report == expected.report


def test_streaming_does_not_stall_on_a_stray_bracket() -> None:
    sanitizer = StreamingCitationSanitizer(ALLOWED)

    first = sanitizer.feed("a [ b")

    assert first == "a [ b"  # released as soon as it cannot be a citation


def test_streaming_hold_is_bounded() -> None:
    sanitizer = StreamingCitationSanitizer(ALLOWED)
    noise = "[" + "S1, " * 40  # looks like a marker forever but never closes

    released = sanitizer.feed(noise)

    assert len(released) > 0
    assert sanitizer.finish() + released == noise


def test_unterminated_marker_is_released_at_the_end() -> None:
    out, sanitizer = _stream(["Answer [S9"])

    assert out == "Answer [S9"
    assert sanitizer.report.removed == ()
