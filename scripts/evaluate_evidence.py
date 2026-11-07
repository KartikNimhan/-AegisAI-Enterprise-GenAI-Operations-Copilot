"""Claim-level evidence evaluation CLI (M10.7). Offline only.

Runs `app.evaluation.evidence.LexicalSupportChecker` over the labelled claim set
(`backend/tests/evaluation/data/evidence_eval_dataset.json` by default) and prints the metrics, the
errors and the support-label gate. It makes no model call, reads no secret, opens no database and
uses no network. The result never changes what the application shows: answers keep
"Retrieved source — support not verified" until the owner decides D-5.

Usage: uv run python scripts/evaluate_evidence.py [--dataset PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.evidence import (  # noqa: E402
    SupportLabelGate,
    evaluate,
    format_report,
    load_evidence_dataset,
)

DEFAULT_DATASET = ROOT / "backend" / "tests" / "evaluation" / "data" / "evidence_eval_dataset.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Claim-level evidence evaluation (M10.7). Offline only."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args(argv)
    report = evaluate(load_evidence_dataset(args.dataset))
    print(format_report(report, SupportLabelGate()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
