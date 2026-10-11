# AegisAI Evaluation — M11 Phase 1 + Phase 2 Step 1

A reusable, version-controlled RAG evaluation dataset and a CLI runner
(`scripts/evaluate.py`) that exercises the **real** retrieval pipeline
against it, plus (Phase 2 Step 1) a committed baseline to compare
against. See the M11 inspection/implementation reports for the full
roadmap and what's deliberately out of scope here.

## What this is not

- **Not a benchmark.** The dataset (`data/rag_eval_dataset.json`) is
  small, synthetic, and topically well-separated on purpose, mirroring
  the existing `rag_fixtures.py`/`test_recall_at_k.py` fixture this was
  built alongside. No claim is made about retrieval quality on any real,
  production-scale corpus.
- **Not an LLM evaluation.** Phase 1 makes **no LLM call at all** — no
  `GROQ_API_KEY` is read, no paid API call happens, no answer text is
  generated. See "Metrics" below for exactly which numbers this
  implies are unavailable, and why they're reported as `"skipped"`
  rather than approximated or faked.

## Running it

```bash
uv run python scripts/evaluate.py
```

Requires a reachable Postgres (`docker compose up -d postgres`) and
downloads/loads the real Sentence Transformers embedding model on first
run (same ~90MB download every other real-model path in this codebase
needs). Writes a JSON report to `data/evaluation/` (gitignored — see
that directory's own `.gitkeep`) and prints a summary to stdout.

All database writes (one synthetic `Document` + its chunks + their
embeddings) happen inside a transaction that is **always rolled back** —
nothing this script does is ever persisted to your real database,
success or failure.

Options: `--dataset <path>`, `--output-dir <path>`, `--top-k <int>`
(default 3), `--baseline <path>`, `--compare-to-baseline`,
`--update-baseline` — see `scripts/evaluate.py --help`.

## Baseline comparison (Phase 2, Step 1)

`data/baseline.json` is a small, committed snapshot of a past run's
metrics — just the summary numbers plus `dataset_version`/`top_k`
(enough to check the comparison is even meaningful), never per-case
detail.

**Generate** it by running a normal evaluation and explicitly asking to
capture it:
```bash
uv run python scripts/evaluate.py --update-baseline
```
This only writes the file if the run was **fully successful** — zero
errored cases, and `recall_at_k`/`context_inclusion_rate`/
`operational_failure_rate` all actually `"computed"` (not skipped due
to a seeding failure). If it wasn't, the command refuses and explains
why instead of capturing a baseline from a broken run.

**Review** the baseline before trusting it: it's a plain JSON file —
open it, check `dataset_version`/`top_k` match what you expect, and
sanity-check the metric values against what you just saw printed.

**Compare** a later run against it:
```bash
uv run python scripts/evaluate.py --compare-to-baseline
```
Prints a per-metric line: `improved`/`regressed`/`unchanged` with the
numeric delta for anything both sides actually computed; `not
comparable` (never a fabricated delta) if either side's metric was
itself skipped or errored; `new_metric`/`MISSING` if a metric exists on
only one side. If the current run's `dataset_version` or `top_k`
doesn't match the baseline's, the whole comparison is skipped with that
reason printed — no delta is ever computed across incompatible runs.

**Update deliberately** after a change you've reviewed and want to
accept as the new normal:
```bash
uv run python scripts/evaluate.py --update-baseline
```
There is no automatic or implicit path to this — a normal run (no
flags, or `--compare-to-baseline` alone) never writes to
`baseline.json`.

**Passing both `--compare-to-baseline --update-baseline` together** is
supported and does exactly what it looks like, in this order: the
comparison against the *current* (about-to-be-replaced) baseline is
printed first, then — only if the run was fully successful — the
baseline is overwritten. This lets you see what's changing before it's
captured. If the run was *not* fully successful, the comparison still
prints (against the still-valid old baseline), but the update is
refused with an explanation and the command exits non-zero; the old
baseline is left untouched either way.

A malformed or corrupted `baseline.json` (bad JSON, or valid JSON
missing a required field) is reported as a plain, clear message under
`--compare-to-baseline` — never an unhandled crash, and the file itself
is never modified by a failed comparison attempt.

## Dataset format

`data/rag_eval_dataset.json`:

```json
{
  "version": 1,
  "corpus": [{"id": "c1", "document_title": "...", "text": "..."}],
  "cases": [
    {
      "id": "q1",
      "question": "...",
      "relevant_chunk_ids": ["c1"],
      "expected_answer_contains": ["some phrase"],
      "category": "retrieval"
    }
  ]
}
```

`relevant_chunk_ids` must reference an `id` present in `corpus` —
`app.evaluation.dataset.load_dataset` validates this and raises
`DatasetValidationError` otherwise, rather than silently accepting a
dataset that could never produce a meaningful result.
`expected_answer_contains` is carried through the schema for forward
compatibility with a future phase that generates real answers — it is
**not read by Phase 1's metrics at all**, since there is no answer to
check it against.

## Metrics, their inputs, and their limitations

| Metric | Computed from | Limitation |
|---|---|---|
| `recall_at_k` | `RetrievalRepository.search`'s raw top-K nearest neighbors (real embedding model, real pgvector) vs. each case's `relevant_chunk_ids` | Same measurement `test_recall_at_k.py` already makes — small/synthetic corpus, not a production benchmark |
| `context_inclusion_rate` | `RetrievalService.retrieve` (applies the similarity-threshold filter) + `ContextAssembler.assemble` (applies the context char-budget truncation) vs. `relevant_chunk_ids` | A *different* number from `recall_at_k`, not a restatement of it: a chunk can be in the raw top-K but dropped by the threshold or truncated out of the context budget. Still synthetic-corpus-only |
| `operational_failure_rate` | Fraction of cases whose retrieval step raised an exception | Only catches exceptions during this evaluation run itself, not every failure mode the real API might hit (e.g. request-level timeouts, which this runner doesn't simulate) |
| `answer_correctness` | — | **Always reported `"skipped"`.** Scoring a generated answer against `expected_answer_contains` requires a real LLM call, which Phase 1 deliberately never makes |
| `citation_precision` | — | **Always reported `"skipped"`,** same reason — this would measure which chunks a model actually chose to cite, which doesn't exist without generating an answer |

If live infrastructure (Postgres, or the embedding model) is unavailable
when the script runs, **every** retrieval-dependent metric above is
reported `"skipped"` with the specific reason (e.g. "Postgres is not
reachable"), and the run exits non-zero — never a fabricated or
best-guess value.

## Files

| Path | Purpose |
|---|---|
| `data/rag_eval_dataset.json` | The dataset itself |
| `data/baseline.json` | Committed snapshot of a past successful run's metrics — see "Baseline comparison" above |
| `backend/app/evaluation/dataset.py` | Loading + validation |
| `backend/app/evaluation/metrics.py` | Pure metric functions (`MetricResult`, `recall_hit`, `recall_at_k`, `context_inclusion_rate`, `operational_failure_rate`, `skipped_metric`) |
| `backend/app/evaluation/baseline.py` | `Baseline` load/save + `compare_to_baseline` (compatibility check, per-metric direction-aware delta) |
| `backend/app/evaluation/runner.py` | Orchestrates a run against the real retrieval pipeline |
| `backend/app/evaluation/report.py` | `EvaluationReport` — JSON serialization + terminal rendering |
| `scripts/evaluate.py` | CLI entrypoint |
| `backend/tests/unit/evaluation/` | Deterministic unit tests (dataset validation, metrics, report serialization, baseline comparison, seeding-failure error handling, and the CLI's own baseline-comparison glue in `test_evaluate_cli.py`) — no live infra |
| `backend/tests/evaluation/test_evaluate_runner.py` | Opt-in integration test of the full runner against real Postgres + the real embedding model (`RUN_EMBEDDING_INTEGRATION=1`) |
