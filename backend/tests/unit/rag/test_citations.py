"""Inline-citation validation: valid ids kept, invalid ids removed, odd brackets left alone,
and the streaming sanitizer gives the same answer however the text is split into chunks."""

from __future__ import annotations

import pytest

from app.rag.citations import StreamingCitationSanitizer, sanitize_citations

ALLOWED = ["S1", "S2"]
# Lenticular brackets, which some models (gpt-oss) write instead of `[` and `]`: 【 and 】.
L, R = "【", "】"
# Whitespace and digits beyond ASCII, which the non-streaming pattern reads as `\s` and `\d`.
NEWLINE, NBSP, IDEOGRAPHIC_SPACE = chr(0x0A), chr(0xA0), chr(0x3000)
FULLWIDTH_ONE, FULLWIDTH_NINE = chr(0xFF11), chr(0xFF19)


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


def test_lenticular_citations_count_and_are_written_back_in_the_canonical_form() -> None:
    # The live failure: the model wrote 【S1】, so no source was marked as cited.
    result = sanitize_citations(f"Held in Larkspur-17 {L}S1{R} and Birch-4 {L}S2{R}.", ALLOWED)

    assert result.text == "Held in Larkspur-17 [S1] and Birch-4 [S2]."
    assert result.report.cited == ("S1", "S2")
    assert result.report.removed == ()


def test_an_unknown_id_in_lenticular_brackets_is_removed_and_reported() -> None:
    result = sanitize_citations(f"The limit is 50 {L}S9{R}.", ALLOWED)

    assert result.text == "The limit is 50."
    assert result.report.removed == ("S9",)
    assert result.report.cited == ()


def test_a_lenticular_group_keeps_only_its_valid_ids() -> None:
    result = sanitize_citations(f"Both apply {L}S1, S7, S2{R}.", ALLOWED)

    assert result.text == "Both apply [S1, S2]."
    assert result.report.cited == ("S1", "S2")
    assert result.report.removed == ("S7",)


def test_a_mixed_bracket_pair_is_still_checked() -> None:
    result = sanitize_citations(f"Mixed [S1{R} and {L}S9].", ALLOWED)

    assert result.text == "Mixed [S1] and."
    assert result.report.cited == ("S1",)
    assert result.report.removed == ("S9",)


def test_lenticular_text_that_only_looks_bracketed_is_not_touched() -> None:
    text = f"See {L}1{R}, {L}Appendix S9{R}, {L}S{R}, {L}s1{R} and {L}S1x{R}."

    result = sanitize_citations(text, ALLOWED)

    assert result.text == text
    assert result.report == sanitize_citations("", ALLOWED).report


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


def test_streaming_lenticular_marker_split_across_chunks_is_validated() -> None:
    out, sanitizer = _stream(["Fact ", L, "S", "9", R, " and ", f"{L}S1", f"{R}."])

    assert out == "Fact  and [S1]."
    assert sanitizer.report.removed == ("S9",)
    assert sanitizer.report.cited == ("S1",)


@pytest.mark.parametrize(
    ("marker", "invalid_id"),
    [
        (f"[S9{NEWLINE}]", "S9"),
        (f"{L}{IDEOGRAPHIC_SPACE}S9{R}", "S9"),
        (f"[S9{NBSP}]", "S9"),
        (f"{L}S{FULLWIDTH_NINE}{R}", f"S{FULLWIDTH_NINE}"),
    ],
)
def test_streaming_checks_markers_with_unicode_whitespace_or_digits(
    marker: str, invalid_id: str
) -> None:
    # The non-streaming pattern already removed these; the stream used to pass them through.
    text = f"Fact {marker} and [S1]."
    expected = sanitize_citations(text, ALLOWED)

    assert expected.text == "Fact  and [S1]."
    assert expected.report.removed == (invalid_id,)
    for parts in ([text], list(text)):
        out, sanitizer = _stream(parts)
        assert out == expected.text
        assert sanitizer.report.removed == (invalid_id,)
        assert sanitizer.report.cited == ("S1",)


@pytest.mark.parametrize(
    "marker", [f"[S1{NEWLINE}]", f"{L}{IDEOGRAPHIC_SPACE}S1{R}", f"[S1,{NBSP}S2]"]
)
def test_valid_markers_with_unicode_whitespace_are_credited_on_both_paths(marker: str) -> None:
    text = f"Fact {marker}."
    expected = sanitize_citations(text, ALLOWED)

    out, sanitizer = _stream(list(text))

    assert expected.text in ("Fact [S1].", "Fact [S1, S2].")
    assert out == expected.text
    assert sanitizer.report == expected.report
    assert expected.report.cited[0] == "S1" and expected.report.removed == ()


def test_a_fullwidth_digit_never_credits_an_ascii_source_id() -> None:
    text = f"Looks like S1: {L}S{FULLWIDTH_ONE}{R} and [S{FULLWIDTH_ONE}]."
    expected = sanitize_citations(text, ALLOWED)

    out, sanitizer = _stream(list(text))

    assert expected.report.cited == () and sanitizer.report.cited == ()
    assert expected.report.removed == (f"S{FULLWIDTH_ONE}",) == sanitizer.report.removed
    assert f"S{FULLWIDTH_ONE}" not in expected.text and f"S{FULLWIDTH_ONE}" not in out
    assert "".join(out.split()) == "".join(expected.text.split())


def test_streaming_unicode_whitespace_marker_split_across_chunks_is_validated() -> None:
    out, sanitizer = _stream(
        ["Fact ", L, IDEOGRAPHIC_SPACE, "S", "9", R, " and [S1", NEWLINE, "]."]
    )

    assert out == "Fact  and [S1]."
    assert sanitizer.report.removed == ("S9",)
    assert sanitizer.report.cited == ("S1",)


def test_ordinary_text_with_these_characters_is_released_at_once_and_unchanged() -> None:
    text = f"Line one{NEWLINE}two{NBSP}100 S1{IDEOGRAPHIC_SPACE}total {FULLWIDTH_NINE} items."
    sanitizer = StreamingCitationSanitizer(ALLOWED)

    # No opening bracket, so nothing is held back: every character comes straight out.
    assert all(sanitizer.feed(char) == char for char in text)
    assert sanitizer.finish() == ""
    assert sanitize_citations(text, ALLOWED).text == text
    # An opening bracket that turns out not to start a citation is released as soon as it cannot.
    assert sanitizer.feed(f"see [S1{NEWLINE}and more") == f"see [S1{NEWLINE}and more"
    assert sanitizer.report == sanitize_citations("", ALLOWED).report


def test_streaming_hold_is_bounded_for_whitespace_too() -> None:
    sanitizer = StreamingCitationSanitizer(ALLOWED)
    noise = L + IDEOGRAPHIC_SPACE * 100  # could be a marker for a while, but never closes

    released = sanitizer.feed(noise)

    assert len(released) > 0
    assert released + sanitizer.finish() == noise


@pytest.mark.parametrize(
    "text",
    [
        "Claim [S1] then [S9], and [S1, S4] plus [x] and [S1.",
        "[[S1]] [S2",
        "no brackets at all",
        "tail [",
        "[S9][S1][S9]",
        f"Claim {L}S1{R} then {L}S9{R}, and {L}S1, S4{R} plus {L}x{R} and {L}S1.",
        f"{L}{L}S1{R}{R} [S2{R} {L}S9]",
        f"tail {L}",
        f"a [S9{NEWLINE}] b {L}{IDEOGRAPHIC_SPACE}S1, S2{R} c [S9{NBSP}] d {L}S{FULLWIDTH_NINE}{R}",
        f"[S1,{NEWLINE}{NBSP}S2] and [S{FULLWIDTH_ONE}] and {L}S1 {IDEOGRAPHIC_SPACE}x",
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
