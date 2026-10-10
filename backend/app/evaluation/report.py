"""The evaluation run's report: a machine-readable structure plus a
concise human-readable rendering of the same data — never two separate
sources of truth for the same numbers.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.evaluation.metrics import MetricResult


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    question: str
    category: str
    status: str  # "ok" | "error"
    duration_ms: float
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    relevant_chunk_ids: list[str] = field(default_factory=list)
    recall_hit: bool | None = None
    context_inclusion_hit: bool | None = None
    error: str | None = None


@dataclass(frozen=True)
class EvaluationReport:
    run_id: str
    dataset_path: str
    dataset_version: int
    git_commit: str | None
    top_k: int
    summary: dict[str, dict]
    cases: list[CaseOutcome]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "dataset_path": self.dataset_path,
            "dataset_version": self.dataset_version,
            "git_commit": self.git_commit,
            "top_k": self.top_k,
            "summary": self.summary,
            "cases": [asdict(case) for case in self.cases],
        }

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        safe_run_id = self.run_id.replace(":", "-")
        out_path = directory / f"report-{safe_run_id}.json"
        out_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return out_path

    def render_summary(self) -> str:
        lines = [
            f"AegisAI Evaluation — {self.run_id} (dataset v{self.dataset_version}"
            + (f", commit {self.git_commit}" if self.git_commit else "")
            + ")",
        ]
        for metric_name, metric in self.summary.items():
            if metric["status"] == "computed":
                lines.append(f"  {metric_name}: {metric['value']:.2f}")
            else:
                lines.append(f"  {metric_name}: {metric['status']} ({metric['reason']})")
        cases_with_errors = [c for c in self.cases if c.status == "error"]
        lines.append(f"  cases: {len(self.cases)} total, {len(cases_with_errors)} errored")
        for case in cases_with_errors:
            lines.append(f"    [ERROR] {case.case_id}: {case.error}")
        return "\n".join(lines)


def metric_to_summary_entry(metric: MetricResult) -> dict:
    return {"status": metric.status, "value": metric.value, "reason": metric.reason}


def current_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None
