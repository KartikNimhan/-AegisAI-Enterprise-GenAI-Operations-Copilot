"""Offline evaluation of citation validity: scripted model answers (some citing sources that were
never retrieved) are scored before and after sanitizing. No model, database or network."""

from __future__ import annotations

import pytest

from app.evaluation.metrics import citation_validity_rate
from app.rag.citations import sanitize_citations

SOURCES = ["S1", "S2", "S3"]

# (scripted model answer, valid ids it cites, invalid ids it cites)
SCRIPTED = [
    ("Leave is 25 days [S1].", 1, 0),
    ("Both rules apply [S1, S2].", 2, 0),
    ("Fabricated [S7] and real [S3].", 1, 1),
    ("Invented only [S9, S12].", 0, 2),
    ("No citations here.", 0, 0),
]


def _counts(answer: str) -> tuple[int, int]:
    report = sanitize_citations(answer, SOURCES).report
    return len(report.cited), len(report.removed)


def test_the_metric_counts_what_the_sanitizer_reports() -> None:
    for answer, valid, invalid in SCRIPTED:
        assert _counts(answer) == (valid, invalid)


def test_raw_model_output_scores_below_one_and_sanitized_output_scores_one() -> None:
    raw = citation_validity_rate([_counts(answer) for answer, _v, _i in SCRIPTED])
    assert raw.status == "computed" and raw.value == pytest.approx(4 / 7)

    sanitized = [sanitize_citations(answer, SOURCES).text for answer, _v, _i in SCRIPTED]
    after = citation_validity_rate([_counts(text) for text in sanitized])
    assert after.status == "computed" and after.value == 1.0


def test_answers_without_citations_are_skipped_not_scored() -> None:
    result = citation_validity_rate([(0, 0)])

    assert result.status == "skipped"
    assert result.reason
