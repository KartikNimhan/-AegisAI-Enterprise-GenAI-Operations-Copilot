"""AegisAI evaluation CLI (M11, Phase 1).

Runs the version-controlled RAG evaluation dataset
(`backend/tests/evaluation/data/rag_eval_dataset.json` by default)
against the REAL retrieval pipeline — the real `LocalEmbeddingProvider`
(downloads/loads the actual Sentence Transformers model on first run,
same as every other real-model path in this codebase) and the real
Postgres/pgvector `RetrievalRepository`/`RetrievalService`/
`ContextAssembler`. Writes a JSON report under `data/evaluation/`
(gitignored — see that directory's own `.gitkeep`) and prints a concise
human-readable summary.

What this does NOT do, and why: it makes no LLM call at all — no
`GROQ_API_KEY` is read or required, no paid API call happens, and no
answer text is generated. Two metrics that would need one
(`answer_correctness`, `citation_precision`) are always reported as
explicitly "skipped" with that reason — never computed against a
fabricated stand-in answer. See `app/evaluation/metrics.py`'s
`SKIPPED_NO_LIVE_LLM` and `app/evaluation/runner.py`'s module docstring
for the full reasoning, and the M11 Phase 1 report for why this scope
boundary was chosen.

All database writes this script makes (one synthetic Document + its
chunks + their embeddings) happen inside a single transaction that is
ALWAYS rolled back at the end, exactly like
`backend/tests/evaluation/conftest.py`'s `db_session` fixture — nothing
this script does is ever persisted, regardless of success or failure.

Usage:
    uv run python scripts/evaluate.py
    uv run python scripts/evaluate.py --dataset path/to/other.json --top-k 5
    uv run python scripts/evaluate.py --output-dir data/evaluation

Run from anywhere — the backend package is located relative to this
file, not the current working directory.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_DEFAULT_DATASET = (
    _REPO_ROOT / "backend" / "tests" / "evaluation" / "data" / "rag_eval_dataset.json"
)
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "data" / "evaluation"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_DEFAULT_DATASET,
        help=f"Path to the evaluation dataset JSON file (default: {_DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help=f"Directory to write the JSON report into (default: {_DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="K for recall_at_k / context_inclusion_rate (default: 3)",
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    # Imported here, after sys.path is patched above, not at module level —
    # these are backend/app modules, not importable before that patch.
    from app.config import get_settings
    from app.db.session import AsyncSessionLocal, check_database
    from app.evaluation.dataset import DatasetValidationError, load_dataset
    from app.evaluation.runner import run_evaluation

    try:
        dataset = load_dataset(args.dataset)
    except DatasetValidationError as exc:
        print(f"Dataset is invalid: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"Could not read dataset {args.dataset}: {exc}", file=sys.stderr)
        return 1

    if not await check_database(timeout=5.0):
        print(
            "Postgres is not reachable (tried for 5s) — start it via "
            "`docker compose up -d postgres` and try again. No metrics "
            "were computed; nothing was written.",
            file=sys.stderr,
        )
        return 1

    print(
        "Loading the real embedding model if not already cached "
        "(first run can take a while on a slow connection)..."
    )
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        try:
            report = await run_evaluation(
                session=session,
                settings=settings,
                dataset=dataset,
                top_k=args.top_k,
                dataset_path=str(args.dataset),
            )
        finally:
            # Never commit — this script's writes are synthetic
            # evaluation data, not real application data. See this
            # module's own docstring.
            await session.rollback()

    out_path = report.write(args.output_dir)
    print(report.render_summary())
    print(f"\nFull report written to {out_path}")
    return 0


def main() -> None:
    args = _parse_args()
    exit_code = asyncio.run(_main_async(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
