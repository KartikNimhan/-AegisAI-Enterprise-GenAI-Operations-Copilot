# AegisAI Evaluation — M11 Phase 1

A reusable, version-controlled RAG evaluation dataset and a CLI runner
(`scripts/evaluate.py`) that exercises the **real** retrieval pipeline
against it. This is Phase 1 only — see the M11 inspection report and
implementation report for the full roadmap and what's deliberately out
of scope here.

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
(default 3) — see `scripts/evaluate.py --help`.

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
| `backend/app/evaluation/dataset.py` | Loading + validation |
| `backend/app/evaluation/metrics.py` | Pure metric functions (`MetricResult`, `recall_hit`, `recall_at_k`, `context_inclusion_rate`, `operational_failure_rate`, `skipped_metric`) |
| `backend/app/evaluation/runner.py` | Orchestrates a run against the real retrieval pipeline |
| `backend/app/evaluation/report.py` | `EvaluationReport` — JSON serialization + terminal rendering |
| `scripts/evaluate.py` | CLI entrypoint |
| `backend/tests/unit/evaluation/` | Deterministic unit tests (dataset validation, metrics, report serialization, seeding-failure error handling) — no live infra |
| `backend/tests/evaluation/test_evaluate_runner.py` | Opt-in integration test of the full runner against real Postgres + the real embedding model (`RUN_EMBEDDING_INTEGRATION=1`) |
