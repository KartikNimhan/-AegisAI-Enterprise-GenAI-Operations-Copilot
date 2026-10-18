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

import app.db.session as session_module  # noqa: E402
import app.evaluation.runner as runner_module  # noqa: E402
from app.evaluation.report import CaseOutcome, EvaluationReport  # noqa: E402


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


# --- --update-baseline guard on no_answer_abstention_rate ----------------
#
# Drives the real `_main_async` end to end, with only its three external
# dependencies replaced: the Postgres reachability check, the DB session,
# and `run_evaluation` itself (which would need a real DB + embedding
# model). The dataset, argument parsing, guard logic, and baseline
# writing are all the real code.

_VALID_DATASET = {
    "version": 2,
    "corpus": [{"id": "c1", "document_title": "Doc", "text": "Some chunk text."}],
    "cases": [{"id": "q1", "question": "A question?", "relevant_chunk_ids": ["c1"]}],
}


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def rollback(self) -> None:
        pass


def _otherwise_successful_report(no_answer_entry: dict) -> EvaluationReport:
    """A fully successful run (one OK case, every retrieval metric
    computed) except for whatever `no_answer_abstention_rate` is given."""
    return EvaluationReport(
        run_id="2026-01-01T00:00:00+00:00",
        dataset_path="dataset.json",
        dataset_version=2,
        git_commit="abc1234",
        top_k=3,
        summary={
            "recall_at_k": {"status": "computed", "value": 1.0, "reason": None},
            "context_inclusion_rate": {"status": "computed", "value": 1.0, "reason": None},
            "operational_failure_rate": {"status": "computed", "value": 0.0, "reason": None},
            "no_answer_abstention_rate": no_answer_entry,
            "answer_correctness": {"status": "skipped", "value": None, "reason": "no live LLM"},
            "citation_precision": {"status": "skipped", "value": None, "reason": "no live LLM"},
        },
        cases=[
            CaseOutcome(
                case_id="q1",
                question="A question?",
                category="retrieval",
                status="ok",
                duration_ms=1.0,
                recall_fraction=1.0,
                context_inclusion_fraction=1.0,
            )
        ],
    )


async def _run_update_baseline(
    report: EvaluationReport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[int, Path]:
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(_VALID_DATASET), encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"

    async def _fake_check_database(timeout: float = 2.0) -> bool:
        return True

    async def _fake_run_evaluation(**_kwargs: object) -> EvaluationReport:
        return report

    monkeypatch.setattr(session_module, "check_database", _fake_check_database)
    monkeypatch.setattr(session_module, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(runner_module, "run_evaluation", _fake_run_evaluation)

    args = evaluate._parse_args(
        [
            "--dataset",
            str(dataset_path),
            "--output-dir",
            str(tmp_path / "reports"),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
        ]
    )
    return await evaluate._main_async(args), baseline_path


async def test_update_baseline_refuses_when_no_answer_abstention_rate_errored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _otherwise_successful_report(
        {"status": "error", "value": None, "reason": "simulated metric failure"}
    )
    # A baseline already exists: it must survive the refused update byte for byte.
    existing = tmp_path / "baseline.json"
    existing.write_text('{"sentinel": "do not overwrite"}\n', encoding="utf-8")

    exit_code, baseline_path = await _run_update_baseline(report, tmp_path, monkeypatch)

    assert exit_code == 1
    assert baseline_path.read_text(encoding="utf-8") == '{"sentinel": "do not overwrite"}\n'
    stderr = capsys.readouterr().err
    assert "Refusing to update the baseline" in stderr
    assert "no_answer_abstention_rate" in stderr


async def test_update_baseline_allows_a_skipped_no_answer_abstention_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dataset with no expect_no_answer case legitimately reports the
    metric as "skipped" — that must not block capturing a baseline."""
    report = _otherwise_successful_report(
        {
            "status": "skipped",
            "value": None,
            "reason": "the dataset has no case with expect_no_answer=true",
        }
    )

    exit_code, baseline_path = await _run_update_baseline(report, tmp_path, monkeypatch)

    assert exit_code == 0
    written = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert written["summary"]["no_answer_abstention_rate"]["status"] == "skipped"
