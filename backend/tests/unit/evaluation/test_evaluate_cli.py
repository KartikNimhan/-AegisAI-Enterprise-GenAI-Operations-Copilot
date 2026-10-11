"""Unit tests for scripts/evaluate.py's `_render_baseline_comparison` —
the `--compare-to-baseline` logic, factored out specifically so it can
be exercised here with a constructed report and a tmp_path baseline
file. No live Postgres, no embedding model, no network: this only
proves the CLI's own glue around app.evaluation.baseline behaves
safely, not the evaluation run itself (that's covered by
backend/tests/unit/evaluation/test_runner_error_handling.py and the
opt-in backend/tests/evaluation/test_evaluate_runner.py).

scripts/ is outside the `backend` package pytest's pythonpath points
at, so the module is loaded directly from its file path rather than via
a normal `import` statement.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "evaluate.py"


def _load_evaluate_module():
    spec = importlib.util.spec_from_file_location("aegisai_evaluate_cli", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluate = _load_evaluate_module()

from app.evaluation.report import EvaluationReport  # noqa: E402


def _report() -> EvaluationReport:
    return EvaluationReport(
        run_id="2026-01-01T00:00:00+00:00",
        dataset_path="dataset.json",
        dataset_version=1,
        git_commit="abc1234",
        top_k=3,
        summary={
            "recall_at_k": {"status": "computed", "value": 1.0, "reason": None},
            "context_inclusion_rate": {"status": "computed", "value": 1.0, "reason": None},
            "operational_failure_rate": {"status": "computed", "value": 0.0, "reason": None},
            "answer_correctness": {"status": "skipped", "value": None, "reason": "no live LLM"},
            "citation_precision": {"status": "skipped", "value": None, "reason": "no live LLM"},
        },
        cases=[],
    )


def test_render_reports_no_baseline_without_crashing(tmp_path: Path) -> None:
    text = evaluate._render_baseline_comparison(_report(), tmp_path / "does-not-exist.json")

    assert "no baseline file" in text


def test_render_handles_a_malformed_baseline_file_without_crashing(tmp_path: Path) -> None:
    """The exact bug this fix addresses: a corrupted baseline.json must
    be reported as a plain string, never an unhandled exception — and
    the file itself must be left completely untouched."""
    path = tmp_path / "baseline.json"
    original_content = "{not valid json at all!!!"
    path.write_text(original_content, encoding="utf-8")

    text = evaluate._render_baseline_comparison(_report(), path)

    assert "Baseline comparison skipped" in text
    assert "not valid JSON" in text
    # Never modified — this is a read/report path, never a write path.
    assert path.read_text(encoding="utf-8") == original_content


def test_render_handles_a_structurally_invalid_but_parseable_baseline(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dataset_version": 1}), encoding="utf-8")

    text = evaluate._render_baseline_comparison(_report(), path)

    assert "Baseline comparison skipped" in text


def test_render_produces_a_real_comparison_for_a_valid_matching_baseline(tmp_path: Path) -> None:
    from app.evaluation.baseline import Baseline, save_baseline

    path = tmp_path / "baseline.json"
    save_baseline(path, Baseline.from_report(_report()))

    text = evaluate._render_baseline_comparison(_report(), path)

    assert "recall_at_k" in text
    assert "unchanged" in text


@pytest.mark.parametrize("flag_value", [True, False])
def test_compare_to_baseline_argument_round_trips(flag_value: bool) -> None:
    argv = ["--compare-to-baseline"] if flag_value else []
    args = evaluate._parse_args(argv)

    assert args.compare_to_baseline is flag_value
