"""Unit tests for app.evaluation.baseline — pure JSON/dataclass logic,
no database, no model, no network. `tmp_path` is used only as a
throwaway location for load/save round-trips.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.baseline import (
    Baseline,
    BaselineLoadError,
    compare_to_baseline,
    load_baseline,
    save_baseline,
)
from app.evaluation.report import EvaluationReport


def _report(**summary_overrides: dict) -> EvaluationReport:
    summary = {
        "recall_at_k": {"status": "computed", "value": 1.0, "reason": None},
        "context_inclusion_rate": {"status": "computed", "value": 1.0, "reason": None},
        "operational_failure_rate": {"status": "computed", "value": 0.0, "reason": None},
        "answer_correctness": {"status": "skipped", "value": None, "reason": "no live LLM"},
        "citation_precision": {"status": "skipped", "value": None, "reason": "no live LLM"},
    }
    summary.update(summary_overrides)
    return EvaluationReport(
        run_id="2026-01-01T00:00:00+00:00",
        dataset_path="dataset.json",
        dataset_version=1,
        git_commit="abc1234",
        top_k=3,
        summary=summary,
        cases=[],
    )


def _baseline(**summary_overrides: dict) -> Baseline:
    report = _report(**summary_overrides)
    return Baseline.from_report(report)


# --- load/save -------------------------------------------------------


def test_load_baseline_returns_none_when_file_does_not_exist(tmp_path: Path) -> None:
    assert load_baseline(tmp_path / "does-not-exist.json") is None


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    baseline = _baseline()
    path = tmp_path / "baseline.json"

    save_baseline(path, baseline)
    loaded = load_baseline(path)

    assert loaded == baseline


def test_save_baseline_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "baseline.json"

    save_baseline(path, _baseline())

    assert path.exists()


def test_load_baseline_rejects_genuinely_malformed_json(tmp_path: Path) -> None:
    """A corrupted/truncated/hand-edited-wrong baseline file must fail
    safely with a clear BaselineLoadError, never an unhandled
    json.JSONDecodeError — this is the exact gap the original
    implementation had: json.loads()'s own exception propagated
    straight out of load_baseline, uncaught by scripts/evaluate.py's
    `except BaselineLoadError` handler."""
    path = tmp_path / "baseline.json"
    path.write_text("{not valid json at all!!!", encoding="utf-8")

    with pytest.raises(BaselineLoadError, match="not valid JSON") as exc_info:
        load_baseline(path)

    # The path is named in the message, and the original
    # JSONDecodeError is preserved as the cause, not swallowed.
    assert str(path) in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_load_baseline_rejects_a_file_missing_a_required_field(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps({"dataset_version": 1, "top_k": 3, "captured_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )

    with pytest.raises(BaselineLoadError, match="summary"):
        load_baseline(path)


def test_baseline_from_report_uses_the_reports_run_id_as_captured_at() -> None:
    report = _report()

    baseline = Baseline.from_report(report)

    assert baseline.captured_at == report.run_id
    assert baseline.dataset_version == report.dataset_version
    assert baseline.top_k == report.top_k


# --- compatibility -----------------------------------------------------


def test_compare_is_incompatible_on_dataset_version_mismatch() -> None:
    report = _report()
    baseline = Baseline.from_report(_report())
    object.__setattr__(baseline, "dataset_version", 2)

    result = compare_to_baseline(report, baseline)

    assert result.compatible is False
    assert result.incompatibility_reason is not None
    assert "dataset_version" in result.incompatibility_reason
    assert result.metrics == []


def test_compare_is_incompatible_on_top_k_mismatch() -> None:
    report = _report()
    baseline = Baseline.from_report(_report())
    object.__setattr__(baseline, "top_k", 5)

    result = compare_to_baseline(report, baseline)

    assert result.compatible is False
    assert result.incompatibility_reason is not None
    assert "top_k" in result.incompatibility_reason
    assert result.metrics == []


# --- matching / improved / regressed -----------------------------------


def test_compare_reports_unchanged_for_identical_values() -> None:
    report = _report()
    baseline = _baseline()

    result = compare_to_baseline(report, baseline)

    recall = next(m for m in result.metrics if m.name == "recall_at_k")
    assert recall.status == "unchanged"
    assert recall.delta == 0.0


def test_compare_reports_improved_for_higher_is_better_metric_increase() -> None:
    report = _report(recall_at_k={"status": "computed", "value": 1.0, "reason": None})
    baseline = _baseline(recall_at_k={"status": "computed", "value": 0.8, "reason": None})

    result = compare_to_baseline(report, baseline)

    recall = next(m for m in result.metrics if m.name == "recall_at_k")
    assert recall.status == "improved"
    assert recall.delta == pytest.approx(0.2)


def test_compare_reports_regressed_for_higher_is_better_metric_decrease() -> None:
    report = _report(recall_at_k={"status": "computed", "value": 0.6, "reason": None})
    baseline = _baseline(recall_at_k={"status": "computed", "value": 0.8, "reason": None})

    result = compare_to_baseline(report, baseline)

    recall = next(m for m in result.metrics if m.name == "recall_at_k")
    assert recall.status == "regressed"
    assert recall.delta == pytest.approx(-0.2)


def test_compare_respects_lower_is_better_direction_for_failure_rate() -> None:
    """operational_failure_rate going UP is a regression, even though the
    numeric delta is positive — the opposite direction from recall_at_k.
    This is the exact case that would be silently wrong without
    per-metric direction awareness."""
    report = _report(operational_failure_rate={"status": "computed", "value": 0.4, "reason": None})
    baseline = _baseline(
        operational_failure_rate={"status": "computed", "value": 0.0, "reason": None}
    )

    result = compare_to_baseline(report, baseline)

    failure_rate = next(m for m in result.metrics if m.name == "operational_failure_rate")
    assert failure_rate.status == "regressed"
    assert failure_rate.delta == pytest.approx(0.4)


def test_compare_respects_lower_is_better_direction_for_failure_rate_improvement() -> None:
    report = _report(operational_failure_rate={"status": "computed", "value": 0.0, "reason": None})
    baseline = _baseline(
        operational_failure_rate={"status": "computed", "value": 0.4, "reason": None}
    )

    result = compare_to_baseline(report, baseline)

    failure_rate = next(m for m in result.metrics if m.name == "operational_failure_rate")
    assert failure_rate.status == "improved"


# --- missing / new / not-comparable metrics -----------------------------


def test_compare_flags_a_metric_missing_from_the_current_run_without_treating_it_as_zero() -> None:
    report = _report()
    # Simulate a metric the baseline has that the current run's summary
    # dict doesn't define at all.
    del report.summary["operational_failure_rate"]
    baseline = _baseline()

    result = compare_to_baseline(report, baseline)

    failure_rate = next(m for m in result.metrics if m.name == "operational_failure_rate")
    assert failure_rate.status == "missing_metric"
    assert failure_rate.current_value is None
    assert failure_rate.baseline_value == 0.0
    assert "MISSING" in result.render()


def test_compare_flags_a_metric_not_present_in_the_baseline_as_new() -> None:
    report = _report()
    baseline = _baseline()
    del baseline.summary["operational_failure_rate"]

    result = compare_to_baseline(report, baseline)

    failure_rate = next(m for m in result.metrics if m.name == "operational_failure_rate")
    assert failure_rate.status == "new_metric"
    assert failure_rate.baseline_value is None


def test_compare_marks_a_skipped_metric_as_not_comparable_never_a_fake_delta() -> None:
    """answer_correctness is always skipped in Phase 1 on both sides —
    must never be reported as "unchanged, delta 0.0", which would imply
    a real, equal measurement that doesn't exist."""
    report = _report()
    baseline = _baseline()

    result = compare_to_baseline(report, baseline)

    answer_correctness = next(m for m in result.metrics if m.name == "answer_correctness")
    assert answer_correctness.status == "not_comparable"
    assert answer_correctness.delta is None


# --- rendering -----------------------------------------------------------


def test_render_reports_incompatibility_reason_directly() -> None:
    report = _report()
    baseline = Baseline.from_report(_report())
    object.__setattr__(baseline, "top_k", 5)

    result = compare_to_baseline(report, baseline)

    assert "top_k mismatch" in result.render()


def test_render_includes_every_metric_line() -> None:
    report = _report(recall_at_k={"status": "computed", "value": 0.6, "reason": None})
    baseline = _baseline(recall_at_k={"status": "computed", "value": 0.8, "reason": None})

    text = compare_to_baseline(report, baseline).render()

    assert "recall_at_k" in text
    assert "regressed" in text
    assert "context_inclusion_rate" in text
