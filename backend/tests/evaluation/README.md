# AegisAI Evaluation — M11 Phase 1 + Phase 2

A reusable, version-controlled RAG evaluation dataset and a CLI runner
(`scripts/evaluate.py`) that exercises the **real** retrieval pipeline
against it, a committed baseline to compare against (Phase 2 Step 1),
and a deterministic multi-agent orchestration evaluation fixture (Phase
2 Step 2). See the M11 inspection/implementation reports for the full
roadmap and what's deliberately out of scope here.

## What this is not

- **Not a benchmark.** The dataset (`data/rag_eval_dataset.json`) is
  small, synthetic, and built from topically distinct policy areas on
  purpose (distinct topics do not guarantee that an unrelated question
  retrieves nothing above the current similarity threshold — see "Live
  run record" below), mirroring the existing `rag_fixtures.py`/`test_recall_at_k.py` fixture this was
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

### Which tests need what

- `backend/tests/unit/evaluation/` — unit-only. No Docker, no model, no
  network. Run with `uv run pytest backend/tests/unit/evaluation`.
- `backend/tests/evaluation/test_multi_agent_evaluation.py`,
  `test_agent_evaluation.py` — unit-only (despite living under
  `tests/evaluation/`). No Docker, no model, no network — every LLM/
  retrieval dependency is a scripted/fake double. Run with
  `uv run pytest backend/tests/evaluation/test_multi_agent_evaluation.py
  backend/tests/evaluation/test_agent_evaluation.py`.
- `backend/tests/evaluation/test_recall_at_k.py`,
  `test_evaluate_runner.py` — **opt-in**, need a reachable Postgres
  (`docker compose up -d postgres`) and the real Sentence Transformers
  embedding model (downloaded/cached on first use). Run with:
  ```bash
  RUN_EMBEDDING_INTEGRATION=1 uv run pytest backend/tests/evaluation -m embedding_integration
  ```
  Without `RUN_EMBEDDING_INTEGRATION=1` set, both are skipped (not
  failed) — this is also why ordinary CI runs never need this variable.

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

`data/rag_eval_dataset.json` (currently **version 2** — see "Dataset
versioning" below):

```json
{
  "version": 2,
  "corpus": [{"id": "c1", "document_title": "...", "text": "..."}],
  "cases": [
    {
      "id": "q1",
      "question": "...",
      "relevant_chunk_ids": ["c1"],
      "expected_answer_contains": ["some phrase"],
      "category": "retrieval"
    },
    {
      "id": "q7",
      "question": "A question the corpus has no evidence for...",
      "relevant_chunk_ids": [],
      "expect_no_answer": true,
      "category": "no_answer"
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
**not read by Phase 1/2's metrics at all**, since there is no generated
answer to check it against.

`expect_no_answer` (Phase 2, default `false`) explicitly marks a case
whose `relevant_chunk_ids` is intentionally empty — the corpus has no
evidence for the question at all. This is a required, explicit
declaration, not inferred: `load_dataset` **rejects** a case with an
empty `relevant_chunk_ids` that doesn't set `expect_no_answer: true`
(so a typo'd/omitted chunk reference can never silently become a
no-answer case), and **rejects** a case that sets `expect_no_answer:
true` while also declaring `relevant_chunk_ids` (so it can never
accidentally both claim and deny evidence).

### Case types in the shipped dataset (v2)

| Case(s) | Type | What it tests |
|---|---|---|
| q1-q5 | ordinary, single relevant chunk | The original Phase 1 cases — unchanged |
| q6 | **multi-relevant-chunk** | Two chunks (`c3`, `c4`) both answer "what are the IT security requirements" — tests partial vs. complete multi-chunk recall (see `recall_at_k` below) |
| q7 | **no-answer** | "What is the company's policy on parental leave?" — none of the six corpus chunks address this. `relevant_chunk_ids: []`, `expect_no_answer: true`. Excluded from `recall_at_k`/`context_inclusion_rate`; scored only by `no_answer_abstention_rate` |
| q8 | **ambiguous** | "What is the time requirement for IT security?" is genuinely underspecified between `c3` ("within the first week") and `c4` ("every ninety days") — both chunks are relevant, but no single phrase answers the question uniquely. Participates in `recall_at_k`/`context_inclusion_rate` exactly like a multi-chunk case (retrieval *should* surface both); **no metric here claims to detect or score the ambiguity itself** — doing that would require judging whether a generated answer handled the ambiguity well, which needs a live LLM (out of scope; see "What this is not") |

## Metrics, their inputs, and their limitations

| Metric | Computed from | Included / excluded | Limitation |
|---|---|---|---|
| `recall_at_k` | Mean, over **ordinary cases only** (`expect_no_answer: false`), of the fraction of each case's `relevant_chunk_ids` found in `RetrievalRepository.search`'s raw top-K (real embedding model, real pgvector) | Excludes every `expect_no_answer: true` case (see below) | A case with one relevant chunk scores 0.0 or 1.0 (identical to Phase 1's plain hit/no-hit); a case with several relevant chunks (q6, q8) can score a partial fraction (e.g. 0.5) if only some are retrieved. Small/synthetic corpus, not a production benchmark |
| `context_inclusion_rate` | Same fraction-of-relevant-found definition as `recall_at_k`, but over `RetrievalService.retrieve` (similarity-threshold filter) + `ContextAssembler.assemble` (context char-budget truncation) | Same ordinary-cases-only set as `recall_at_k` | A *different* number from `recall_at_k`, not a restatement of it: a chunk can be in the raw top-K but dropped by the threshold or truncated out of the context budget (see `test_context_inclusion_rate_drops_below_recall_at_k_when_the_configured_threshold_excludes_a_relevant_chunk` in `test_threshold_sensitivity.py` for a worked example against the real `RetrievalService`). Still synthetic-corpus-only |
| `no_answer_abstention_rate` | Fraction of `expect_no_answer: true` cases for which `RetrievalService.retrieve` returned **zero** results — i.e. nothing cleared the real, configured `rag_similarity_threshold` | Only `expect_no_answer: true` cases (q7 in the shipped dataset) | **Not** proof the system "knows" it lacks an answer in any deeper sense — only that the configured threshold happened to exclude everything for this question against a small synthetic corpus of distinct topics (which does not guarantee zero results — see "Live run record" below). The retrieval API has no separate "no evidence exists" signal distinct from "nothing matched the threshold" — this metric measures the latter, which is the same signal `ResearchAgentService` already uses in production to say "no relevant evidence was found." `"skipped"` (never `"error"` or a fabricated 0.0) if the dataset has no such case at all |
| `operational_failure_rate` | Fraction of **all** cases (ordinary and no-answer) whose retrieval step raised an exception | All cases | Only catches exceptions during this evaluation run itself, not every failure mode the real API might hit (e.g. request-level timeouts, which this runner doesn't simulate) |
| `answer_correctness` | — | — | **Always reported `"skipped"`.** Scoring a generated answer against `expected_answer_contains` requires a real LLM call, which this evaluation framework deliberately never makes |
| `citation_precision` | — | — | **Always reported `"skipped"`,** same reason — this would measure which chunks a model actually chose to cite, which doesn't exist without generating an answer |

**Why a no-answer case is never folded into `recall_at_k`:** an earlier
version of `recall_hit` treated an empty `relevant_chunk_ids` as a
trivial pass ("nothing to recall, so count it as a hit"). That is
exactly backwards for a no-answer case — it would make `recall_at_k`
look *better* every time a no-answer case was added, regardless of
retrieval quality. `app.evaluation.metrics.recall_fraction` now raises
if given an empty relevant set; the runner excludes `expect_no_answer`
cases from the calculation entirely and reports on them only via
`no_answer_abstention_rate`. Every report (`EvaluationReport.
render_summary`) states exactly how many cases were scored by
`recall_at_k`/`context_inclusion_rate` vs. excluded as no-answer.

If live infrastructure (Postgres, or the embedding model) is unavailable
when the script runs, **every** retrieval-dependent metric above is
reported `"skipped"` with the specific reason (e.g. "Postgres is not
reachable"), and the run exits non-zero — never a fabricated or
best-guess value.

## Live run record: 2026-10-18 (dataset v2)

The first live run of `scripts/evaluate.py` against the version 2
dataset, recorded here as a **measurement**, not as a quality target.

| Item | Value |
|---|---|
| Run | 2026-10-18 15:46 UTC |
| Commit | `6cb5fee` |
| Dataset | version 2, 8 cases |
| `top_k` | 3 |
| Errored cases | 0 |

| Metric | Result |
|---|---|
| `recall_at_k` | 1.0 (computed) |
| `context_inclusion_rate` | 1.0 (computed) |
| `operational_failure_rate` | 0.0 (computed) |
| `no_answer_abstention_rate` | 0.0 (computed) |
| `answer_correctness` | skipped — Phase 1 makes no live LLM call |
| `citation_precision` | skipped — Phase 1 makes no live LLM call |

**The `q7` finding.** `q7` ("What is the company's policy on parental
leave?") is marked `expect_no_answer: true`, but its
`no_answer_abstained` was `false`: at least one retrieved chunk scored
at or above the configured `rag_similarity_threshold`, so the
retrieval step did not come back empty. That is what
`no_answer_abstention_rate = 0.0` (0 of 1 no-answer case) records.
The 0.00 comes from exactly one no-answer case (`q7`), so with this
dataset the metric can only be 0.0 or 1.0.
This result is consistent with the current implementation. It remains
an observed limitation of no-answer retrieval on this dataset; it has
not been investigated further or fixed.

**The threshold margin is unknown.** The JSON report stores each
case's retrieved chunk ids but not their similarity scores, so this
run cannot show how far above (or how close to) the threshold `q7`'s
best chunk was.

**What the metric measures.** `no_answer_abstention_rate` measures
*retrieval* abstention: whether zero results remained after the
similarity threshold was applied. It does not measure whether a
generated LLM answer refuses to answer. In production, a question that
clears the threshold still reaches the LLM, whose prompt tells it to say
so plainly when the context is insufficient; this framework never calls
the LLM, so that final-answer behavior is not evaluated.

**How to read it.** This is a measurement on a small, synthetic,
eight-case dataset. It is not evidence that no-answer handling meets
any quality target, and no such target is defined in this repository.
Answer correctness, citation precision, and final-answer refusal all
remain unmeasured in Phase 1.
The production `rag_similarity_threshold` should not be tuned against
this dataset (see "Retrieval-threshold coverage" below).

The committed evaluation baseline at
`backend/tests/evaluation/data/baseline.json` was not updated by this
run; it stayed at `dataset_version: 1` until it was deliberately
regenerated later the same day (see "Dataset versioning"). The run's
JSON report was written to `data/evaluation/`, which is gitignored.

## Retrieval-threshold coverage (Phase 2, item 4)

`RetrievalService`'s similarity-threshold filtering (both the
configured default and a caller-supplied override) is already covered
deterministically, with controlled fixtures and no DB/model, in
`backend/tests/unit/rag/test_retrieval_service.py`
(`test_results_below_the_similarity_threshold_are_excluded`,
`test_caller_supplied_threshold_overrides_the_configured_default`).
Rather than duplicate that coverage or tune the production default
against this tiny eight-case synthetic dataset,
`backend/tests/unit/evaluation/test_threshold_sensitivity.py` drives the
**real** `RetrievalService.retrieve` against a `FakeRetrievalStrategy`
with results on opposite sides of a configured `rag_similarity_threshold`
(the same doubles `test_retrieval_service.py` itself uses), reads
`outcome.candidates` (unfiltered) vs. `outcome.results` (threshold
-filtered) off that real call, and feeds both into `recall_fraction`/
`context_inclusion_rate` — proving `context_inclusion_rate` is genuinely
downstream of the real filtering logic, not a restatement of
`recall_at_k` under a different name and not a test of metric arithmetic
alone. (An earlier version of this coverage lived in `test_metrics.py`
and only fed hand-constructed id sets straight into the metric
functions, without ever calling `RetrievalService` — it claimed to prove
threshold sensitivity but didn't actually exercise the filter; it has
been replaced.) **No production retrieval default was changed**, and no new
"threshold quality" metric was invented — a metric claiming to show how
retrieval quality changes *across* threshold values would need either
changing production config per evaluation run (not something this
framework does) or an LLM judging whether a given threshold's
inclusion/exclusion decisions were "correct", which needs real answer
generation (out of scope here).

## Multi-agent evaluation (Phase 2, item 5)

`backend/tests/unit/multi_agent/` already has thorough, deterministic
coverage of `MultiAgentOrchestrator` (routing, parallel/sequential
execution, Analyst synthesis, partial failure, timeout, prompt-injection
safety, observability events) driven through the real
`POST /api/v1/multi-agent/run` endpoint with a scripted LLM gateway and
fake retrieval strategy (`tests/unit/multi_agent/conftest.py`'s
`orchestrator_env`/`async_client` fixtures) — no live LLM, DB, or
network call.

`multi_agent_fixtures.py` + `test_multi_agent_evaluation.py` package a
small, named subset of that same kind of scenario into the evaluation
suite's scenario-table/pass-fail-summary form — the same shape
`agent_fixtures.py`/`test_agent_evaluation.py` already gives the
single-agent path — so the M11 evaluation report has an entry for
multi-agent behavior alongside its single-agent counterpart. It reuses
the existing `orchestrator_env`/`async_client` harness directly (via a
re-export in `backend/tests/evaluation/conftest.py`) rather than
building a second mocking seam, and asserts only observable outcomes:
the expected agent path (`agents_used`), citation/source metadata
retention across a tier1 → Analyst handoff (`sources[].filename`), and
graceful partial-failure handling. It does **not** claim anything about
a *live* model choosing the right route unprompted — routing itself is
still the deterministic keyword-based `app.multi_agent.router.route`,
not an LLM decision, in both this fixture and the orchestrator itself.

## Dataset versioning

`version` in the dataset JSON is the compatibility key
`app.evaluation.baseline.compare_to_baseline` checks **before** computing
any per-metric delta — a mismatch means "skip the comparison entirely,"
never "compare numbers measured under different conditions." Phase 2
bumped it from 1 to 2 when q6/q7/q8 were added: even though the *metric
formulas* for q1-q5 are unchanged (a single-relevant-chunk case scores
identically under the old boolean `recall_hit` and the new fractional
`recall_fraction`), the aggregate `recall_at_k`/`context_inclusion_rate`
values themselves change because they're now averaged over more cases,
and a new case type (no-answer) is excluded from them by design. Compare
against a `version: 1`-captured baseline would otherwise silently mix
numbers from a 5-case and an 8-case run under the same metric name.

**Baseline history.** The original `baseline.json` was
`dataset_version: 1` (captured against the original 5-case dataset,
before this Phase 2 change). It was deliberately kept at version 1
after the dataset moved to version 2, because regenerating it requires
a live evaluation run and is a separate, explicit, reviewed action
(`--update-baseline`), never an automatic side effect of a dataset
change. While it was still version 1, `--compare-to-baseline` correctly
reported `"dataset_version mismatch (current 2, baseline 1)"` and
skipped the comparison — the compatibility check working as designed,
not a bug.

**Current baseline.** On 2026-10-18 it was deliberately regenerated with
`--update-baseline`: `dataset_version: 2`, `top_k: 3`, captured at
`2026-10-18T16:10:07+00:00` from commit `11b904a`. Its computed metrics
are `recall_at_k` 1.0, `context_inclusion_rate` 1.0,
`operational_failure_rate` 0.0 and `no_answer_abstention_rate` 0.0;
`answer_correctness` and `citation_precision` remain skipped. The
`no_answer_abstention_rate` value keeps the limitations documented
above: it measures *retrieval* abstention only (zero results after the
similarity threshold), it comes from a single no-answer case (`q7`) so
it can only be 0.0 or 1.0, and it does not measure whether an LLM
refuses to answer. The baseline is a regression-tracking reference for
current behavior, not a quality target.

## Files

| Path | Purpose |
|---|---|
| `data/rag_eval_dataset.json` | The dataset itself (version 2 — see "Dataset versioning") |
| `data/baseline.json` | Committed snapshot of a past successful run's metrics (now version 2, captured 2026-10-18T16:10:07+00:00 from commit `11b904a`; originally version 1 — see "Dataset versioning") — see "Baseline comparison" above |
| `backend/app/evaluation/dataset.py` | Loading + validation, including `expect_no_answer` classification |
| `backend/app/evaluation/metrics.py` | Pure metric functions (`MetricResult`, `recall_fraction`, `recall_at_k`, `context_inclusion_rate`, `operational_failure_rate`, `no_answer_abstention_rate`, `skipped_metric`) |
| `backend/app/evaluation/baseline.py` | `Baseline` load/save + `compare_to_baseline` (compatibility check, per-metric direction-aware delta) |
| `backend/app/evaluation/runner.py` | Orchestrates a run against the real retrieval pipeline; routes `expect_no_answer` cases to `no_answer_abstention_rate` instead of `recall_at_k`/`context_inclusion_rate` |
| `backend/app/evaluation/report.py` | `EvaluationReport` — JSON serialization + terminal rendering (states included/excluded case counts) |
| `scripts/evaluate.py` | CLI entrypoint |
| `backend/tests/unit/evaluation/` | Deterministic unit tests (dataset validation incl. no-answer classification, metrics incl. multi-chunk/no-answer/threshold-sensitivity, report serialization, baseline comparison, seeding-failure error handling, and the CLI's own baseline-comparison glue in `test_evaluate_cli.py`) — no live infra |
| `backend/tests/evaluation/test_evaluate_runner.py` | Opt-in integration test of the full runner against real Postgres + the real embedding model (`RUN_EMBEDDING_INTEGRATION=1`) — now also asserts the shipped no-answer case is excluded from recall/context-inclusion and scored via `no_answer_abstention_rate` |
| `backend/tests/evaluation/multi_agent_fixtures.py`, `test_multi_agent_evaluation.py` | Deterministic multi-agent orchestration evaluation fixture (Phase 2 item 5) — no live infra |
