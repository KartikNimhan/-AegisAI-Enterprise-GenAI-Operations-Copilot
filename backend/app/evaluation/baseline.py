"""Baseline comparison: a committed, version-controlled snapshot of a
past evaluation run's summary metrics, and the logic to compare a new
run against it.

The baseline is intentionally minimal — just the summary metrics plus
enough metadata (`dataset_version`, `top_k`) to check compatibility
before ever computing a delta (see `compare_to_baseline`: a mismatch on
either returns `compatible=False` and no per-metric deltas at all,
rather than comparing numbers measured under different conditions). It
never includes per-case detail — that's what the per-run JSON report
(gitignored, under `data/evaluation/`) is already for.

Updating the baseline is always an explicit, separate action
(`scripts/evaluate.py --update-baseline`) — nothing in this module
writes to a baseline file as a side effect of comparing against it. See
`backend/tests/evaluation/README.md` for the full workflow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.evaluation.report import EvaluationReport

ComparisonStatus = Literal[
    "improved", "regressed", "unchanged", "not_comparable", "new_metric", "missing_metric"
]

# Metrics where a LOWER value is better. Every metric not listed here is
# assumed higher-is-better. Explicit and visible rather than a silent
# per-metric assumption baked into the comparison math — see
# compare_to_baseline's use of this below.
_LOWER_IS_BETTER = {"operational_failure_rate"}


@dataclass(frozen=True)
class Baseline:
    dataset_version: int
    top_k: int
    captured_at: str
    git_commit: str | None
    summary: dict[str, dict]

    def to_dict(self) -> dict:
        return {
            "dataset_version": self.dataset_version,
            "top_k": self.top_k,
            "captured_at": self.captured_at,
            "git_commit": self.git_commit,
            "summary": self.summary,
        }

    @staticmethod
    def from_report(report: EvaluationReport) -> Baseline:
        """`captured_at` is the source run's own `run_id` — the baseline
        is a snapshot *of* that run, not a separately-timestamped event."""
        return Baseline(
            dataset_version=report.dataset_version,
            top_k=report.top_k,
            captured_at=report.run_id,
            git_commit=report.git_commit,
            summary=report.summary,
        )


class BaselineLoadError(ValueError):
    """Raised for a baseline file that exists but can't be used — either
    its content isn't valid JSON at all, or it parses but is missing a
    required field. Always chains the original exception (`raise ...
    from exc`) so the real cause (e.g. the exact JSON syntax error) is
    never lost. Never raised for "the file doesn't exist" — that's a
    normal, expected state (e.g. the very first run) represented by
    `load_baseline` returning `None`, not an error."""


def load_baseline(path: Path) -> Baseline | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineLoadError(f"{path}: not valid JSON ({exc})") from exc
    for required in ("dataset_version", "top_k", "captured_at", "summary"):
        if required not in raw:
            raise BaselineLoadError(f"{path}: missing required field {required!r}")
    return Baseline(
        dataset_version=raw["dataset_version"],
        top_k=raw["top_k"],
        captured_at=raw["captured_at"],
        git_commit=raw.get("git_commit"),
        summary=raw["summary"],
    )


def save_baseline(path: Path, baseline: Baseline) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline.to_dict(), indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class MetricComparison:
    name: str
    status: ComparisonStatus
    current_value: float | None
    baseline_value: float | None
    delta: float | None
    detail: str | None = None


@dataclass(frozen=True)
class ComparisonResult:
    compatible: bool
    incompatibility_reason: str | None
    metrics: list[MetricComparison]

    def render(self) -> str:
        if not self.compatible:
            return f"Baseline comparison skipped: {self.incompatibility_reason}"
        lines = ["Baseline comparison:"]
        for m in self.metrics:
            if m.status == "new_metric":
                lines.append(
                    f"  {m.name}: {_fmt(m.current_value)} (no baseline value — new metric)"
                )
            elif m.status == "missing_metric":
                lines.append(
                    f"  {m.name}: MISSING from current run (baseline had {_fmt(m.baseline_value)})"
                )
            elif m.status == "not_comparable":
                lines.append(f"  {m.name}: not comparable ({m.detail})")
            else:
                # Plain ASCII only — Windows' default console codepage
                # (cp1252) can't encode U+25B2/U+25BC/U+0394 and raises
                # UnicodeEncodeError on print(), not just mojibake.
                symbol = {"improved": "UP", "regressed": "DOWN", "unchanged": "="}[m.status]
                lines.append(
                    f"  {m.name}: {_fmt(m.current_value)} vs baseline "
                    f"{_fmt(m.baseline_value)} ({symbol} {m.status}, delta {m.delta:+.3f})"
                )
        return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def compare_to_baseline(report: EvaluationReport, baseline: Baseline) -> ComparisonResult:
    """Compatibility (same dataset version, same top_k) is checked
    FIRST — if either differs, no per-metric delta is computed at all,
    since the numbers would not be measuring the same thing."""
    if report.dataset_version != baseline.dataset_version:
        return ComparisonResult(
            compatible=False,
            incompatibility_reason=(
                f"dataset_version mismatch (current {report.dataset_version}, "
                f"baseline {baseline.dataset_version})"
            ),
            metrics=[],
        )
    if report.top_k != baseline.top_k:
        return ComparisonResult(
            compatible=False,
            incompatibility_reason=(
                f"top_k mismatch (current {report.top_k}, baseline {baseline.top_k})"
            ),
            metrics=[],
        )

    metric_names = sorted(set(report.summary) | set(baseline.summary))
    comparisons: list[MetricComparison] = []
    for name in metric_names:
        current = report.summary.get(name)
        base = baseline.summary.get(name)

        if current is None:
            # Present in the baseline but not in this run's summary at
            # all — never silently dropped/ignored, always surfaced.
            comparisons.append(
                MetricComparison(
                    name, "missing_metric", None, base.get("value") if base else None, None
                )
            )
            continue
        if base is None:
            comparisons.append(
                MetricComparison(name, "new_metric", current.get("value"), None, None)
            )
            continue
        if current["status"] != "computed" or base["status"] != "computed":
            comparisons.append(
                MetricComparison(
                    name,
                    "not_comparable",
                    current.get("value"),
                    base.get("value"),
                    None,
                    detail=f"current={current['status']!r}, baseline={base['status']!r}",
                )
            )
            continue

        delta = current["value"] - base["value"]
        lower_is_better = name in _LOWER_IS_BETTER
        if abs(delta) < 1e-9:
            status: ComparisonStatus = "unchanged"
        elif (delta > 0) != lower_is_better:
            status = "improved"
        else:
            status = "regressed"
        comparisons.append(MetricComparison(name, status, current["value"], base["value"], delta))

    return ComparisonResult(compatible=True, incompatibility_reason=None, metrics=comparisons)
