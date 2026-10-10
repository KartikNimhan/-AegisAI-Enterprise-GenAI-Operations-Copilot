"""Unit tests for app.evaluation.report — serialization and rendering,
no database, no model, no network. `tmp_path` is used only as a
throwaway directory for the write() round-trip, never touching
data/evaluation/ or any real project path.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.metrics import MetricResult
from app.evaluation.report import CaseOutcome, EvaluationReport, metric_to_summary_entry


def _sample_report() -> EvaluationReport:
    return EvaluationReport(
        run_id="2026-01-01T00:00:00+00:00",
        dataset_path="backend/tests/evaluation/data/rag_eval_dataset.json",
        dataset_version=1,
        git_commit="abc1234",
        top_k=3,
        summary={
            "recall_at_k": {"status": "computed", "value": 0.8, "reason": None},
            "answer_correctness": {
                "status": "skipped",
                "value": None,
                "reason": "requires a live LLM",
            },
        },
        cases=[
            CaseOutcome(
                case_id="q1",
                question="What?",
                category="retrieval",
                status="ok",
                duration_ms=12.5,
                retrieved_chunk_ids=["x1"],
                relevant_chunk_ids=["x1"],
                recall_hit=True,
                context_inclusion_hit=True,
            ),
            CaseOutcome(
                case_id="q2",
                question="Broken?",
                category="retrieval",
                status="error",
                duration_ms=3.1,
                relevant_chunk_ids=["x2"],
                error="RuntimeError: boom",
            ),
        ],
    )


def test_to_dict_round_trips_through_json(tmp_path: Path) -> None:
    report = _sample_report()

    serialized = json.dumps(report.to_dict())
    deserialized = json.loads(serialized)

    assert deserialized["run_id"] == "2026-01-01T00:00:00+00:00"
    assert deserialized["summary"]["recall_at_k"]["value"] == 0.8
    assert deserialized["cases"][1]["status"] == "error"
    assert deserialized["cases"][1]["error"] == "RuntimeError: boom"


def test_write_creates_a_file_named_after_the_run_id(tmp_path: Path) -> None:
    report = _sample_report()

    out_path = report.write(tmp_path)

    assert out_path.exists()
    assert out_path.parent == tmp_path
    # Colons aren't valid in filenames on Windows — must be sanitized.
    assert ":" not in out_path.name
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["dataset_version"] == 1


def test_write_creates_the_output_directory_if_missing(tmp_path: Path) -> None:
    report = _sample_report()
    nested = tmp_path / "does" / "not" / "exist" / "yet"

    out_path = report.write(nested)

    assert out_path.exists()


def test_render_summary_includes_computed_and_skipped_metrics() -> None:
    report = _sample_report()

    text = report.render_summary()

    assert "recall_at_k: 0.80" in text
    assert "answer_correctness: skipped (requires a live LLM)" in text


def test_render_summary_reports_case_count_and_errors() -> None:
    report = _sample_report()

    text = report.render_summary()

    assert "cases: 2 total, 1 errored" in text
    assert "[ERROR] q2: RuntimeError: boom" in text


def test_metric_to_summary_entry_preserves_all_fields() -> None:
    metric = MetricResult(name="recall_at_k", status="computed", value=0.5, reason=None)

    entry = metric_to_summary_entry(metric)

    assert entry == {"status": "computed", "value": 0.5, "reason": None}
