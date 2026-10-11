"""Unit tests for app.evaluation.metrics — pure functions, no I/O."""

from __future__ import annotations

import pytest

from app.evaluation import metrics


def test_recall_fraction_is_one_when_the_single_relevant_id_was_retrieved() -> None:
    assert metrics.recall_fraction({"a", "b", "c"}, {"b"}) == pytest.approx(1.0)


def test_recall_fraction_is_zero_when_no_relevant_id_was_retrieved() -> None:
    assert metrics.recall_fraction({"a", "b", "c"}, {"z"}) == pytest.approx(0.0)


def test_recall_fraction_rejects_an_empty_relevant_set() -> None:
    """A case with no relevant chunk (a no-answer case) must never be
    passed to this function — there is nothing to compute recall over,
    and a trivial 1.0 would silently inflate recall_at_k every time a
    no-answer case exists. Callers exclude those cases entirely; see
    app.evaluation.runner."""
    with pytest.raises(ValueError, match="non-empty"):
        metrics.recall_fraction({"a", "b"}, set())


def test_recall_fraction_does_not_require_exact_set_equality() -> None:
    # Retrieving extra, irrelevant chunks alongside the relevant one is
    # still full recall — recall, not precision.
    assert metrics.recall_fraction({"a", "b", "relevant"}, {"relevant"}) == pytest.approx(1.0)


def test_recall_fraction_is_partial_for_a_multi_relevant_chunk_case() -> None:
    """A case with more than one relevant chunk reports the fraction
    actually found, not a collapsed any-hit boolean — finding one of two
    relevant chunks is 0.5, not simply "a hit"."""
    result = metrics.recall_fraction({"a", "relevant1"}, {"relevant1", "relevant2"})
    assert result == pytest.approx(0.5)


def test_recall_fraction_is_one_when_all_relevant_chunks_are_found() -> None:
    retrieved = {"relevant1", "relevant2", "extra"}
    result = metrics.recall_fraction(retrieved, {"relevant1", "relevant2"})
    assert result == pytest.approx(1.0)


def test_recall_fraction_is_zero_when_none_of_several_relevant_chunks_are_found() -> None:
    assert metrics.recall_fraction({"a", "b"}, {"relevant1", "relevant2"}) == pytest.approx(0.0)


def test_recall_at_k_averages_fractions() -> None:
    result = metrics.recall_at_k([1.0, 1.0, 0.0, 1.0])

    assert result.status == "computed"
    assert result.value == pytest.approx(0.75)


def test_recall_at_k_reflects_partial_multi_chunk_recall() -> None:
    result = metrics.recall_at_k([1.0, 0.5])

    assert result.status == "computed"
    assert result.value == pytest.approx(0.75)


def test_recall_at_k_errors_on_an_empty_input() -> None:
    result = metrics.recall_at_k([])

    assert result.status == "error"
    assert result.reason


def test_context_inclusion_rate_averages_fractions() -> None:
    result = metrics.context_inclusion_rate([1.0, 0.0])

    assert result.status == "computed"
    assert result.value == pytest.approx(0.5)


def test_context_inclusion_rate_errors_on_an_empty_input() -> None:
    result = metrics.context_inclusion_rate([])

    assert result.status == "error"
    assert result.reason


def test_operational_failure_rate_computes_fraction() -> None:
    result = metrics.operational_failure_rate(failure_count=1, total_count=4)

    assert result.status == "computed"
    assert result.value == pytest.approx(0.25)


def test_operational_failure_rate_errors_when_no_cases_ran() -> None:
    result = metrics.operational_failure_rate(failure_count=0, total_count=0)

    assert result.status == "error"


def test_no_answer_abstention_rate_computes_fraction_of_empty_results() -> None:
    result = metrics.no_answer_abstention_rate([True, False, True])

    assert result.status == "computed"
    assert result.value == pytest.approx(2 / 3)


def test_no_answer_abstention_rate_is_skipped_not_errored_when_no_such_case_exists() -> None:
    """A dataset with zero expect_no_answer cases is a normal, valid
    shape — this must be reported as a legitimate "skipped", never an
    "error", and never a fabricated 0.0/1.0 standing in for "no data"."""
    result = metrics.no_answer_abstention_rate([])

    assert result.status == "skipped"
    assert result.reason


def test_skipped_metric_carries_a_reason() -> None:
    result = metrics.skipped_metric("answer_correctness", metrics.SKIPPED_NO_LIVE_LLM)

    assert result.status == "skipped"
    assert result.value is None
    assert result.reason == metrics.SKIPPED_NO_LIVE_LLM


def test_metric_result_rejects_computed_status_without_a_value() -> None:
    with pytest.raises(ValueError, match="no value"):
        metrics.MetricResult(name="x", status="computed", value=None)


def test_metric_result_rejects_skipped_status_without_a_reason() -> None:
    with pytest.raises(ValueError, match="no reason"):
        metrics.MetricResult(name="x", status="skipped", reason=None)


# Threshold-sensitivity coverage (M11 Phase 2, item 4) lives in
# test_threshold_sensitivity.py, not here — it needs to drive the real
# RetrievalService/FakeRetrievalStrategy threshold-filtering path, which
# this file's pure-metric-function tests deliberately don't touch. An
# earlier version of this file had two tests here that only fed
# hand-constructed sets straight into recall_fraction/
# context_inclusion_rate — that tested this file's own arithmetic, not
# threshold filtering, despite claiming to; see
# test_threshold_sensitivity.py's module docstring for the fix.
