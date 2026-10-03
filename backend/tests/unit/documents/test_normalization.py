"""Unit tests for text normalization."""

from __future__ import annotations

from app.documents.normalization import normalize_text


def test_normalizes_crlf_and_cr_line_endings() -> None:
    assert normalize_text("line one\r\nline two\rline three") == "line one\nline two\nline three"


def test_collapses_repeated_horizontal_whitespace() -> None:
    assert normalize_text("a    b\tc") == "a b c"


def test_strips_trailing_whitespace_per_line() -> None:
    assert normalize_text("line one   \nline two\t\n") == "line one\nline two"


def test_collapses_excessive_blank_lines_to_one() -> None:
    result = normalize_text("paragraph one\n\n\n\n\nparagraph two")
    assert result == "paragraph one\n\nparagraph two"


def test_preserves_a_single_paragraph_boundary() -> None:
    result = normalize_text("paragraph one\n\nparagraph two")
    assert result == "paragraph one\n\nparagraph two"


def test_preserves_single_newlines_within_a_paragraph() -> None:
    # A single line break is not "excessive" and must not be collapsed —
    # it may be meaningful (e.g. inside a code block or list).
    result = normalize_text("line one\nline two")
    assert result == "line one\nline two"


def test_strips_leading_bom() -> None:
    assert normalize_text("﻿Hello") == "Hello"


def test_normalizes_unicode_to_nfc() -> None:
    # "e" + combining acute accent (NFD) should canonicalize to "é" (NFC).
    decomposed = "café"
    assert normalize_text(decomposed) == "café"


def test_strips_overall_leading_and_trailing_whitespace() -> None:
    assert normalize_text("   \n  Hello World  \n   ") == "Hello World"


def test_empty_string_stays_empty() -> None:
    assert normalize_text("") == ""


def test_does_not_rewrite_ordinary_content() -> None:
    text = "This is a normal sentence with no issues at all."
    assert normalize_text(text) == text
