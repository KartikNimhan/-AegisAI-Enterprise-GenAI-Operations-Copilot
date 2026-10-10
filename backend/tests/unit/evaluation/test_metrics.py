"""Unit tests for app.evaluation.metrics — pure functions, no I/O."""

from __future__ import annotations

import pytest

from app.evaluation import metrics


def test_recall_hit_true_when_a_relevant_id_was_retrieved() -> None:
    assert metrics.recall_hit({"a", "b", "c"}, {"b"}) is True


def test_recall_hit_false_when_no_relevant_id_was_retrieved() -> None:
    assert metrics.recall_hit({"a", "b", "c"}, {"z"}) is False


def test_recall_hit_true_when_no_relevant_ids_exist_for_the_case() -> None:
    """A case that legitimately has no relevant chunk (e.g. a question the
    corpus has no answer to) is trivially satisfied — there's nothing to
    fail to recall."""
    assert metrics.recall_hit({"a", "b"}, set()) is True


def test_recall_hit_does_not_require_exact_set_equality() -> None:
    # Retrieving extra, irrelevant chunks alongside the relevant one is
    # still a hit — recall, not precision.
    assert metrics.recall_hit({"a", "b", "relevant"}, {"relevant"}) is True


def test_recall_at_k_averages_hits() -> None:
    result = metrics.recall_at_k([True, True, False, True])

    assert result.status == "computed"
    assert result.value == pytest.approx(0.75)


def test_recall_at_k_errors_on_an_empty_input() -> None:
    result = metrics.recall_at_k([])

    assert result.status == "error"
    assert result.reason


def test_context_inclusion_rate_averages_hits() -> None:
    result = metrics.context_inclusion_rate([True, False])

    assert result.status == "computed"
    assert result.value == pytest.approx(0.5)


def test_operational_failure_rate_computes_fraction() -> None:
    result = metrics.operational_failure_rate(failure_count=1, total_count=4)

    assert result.status == "computed"
    assert result.value == pytest.approx(0.25)


def test_operational_failure_rate_errors_when_no_cases_ran() -> None:
    result = metrics.operational_failure_rate(failure_count=0, total_count=0)

    assert result.status == "error"


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
