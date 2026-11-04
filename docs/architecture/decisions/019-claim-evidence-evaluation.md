# 19. Claim-Level Evidence Evaluation (M10.7)

## Status

**Proposed** — 2026-11-04. Not accepted: the owner decides ADR 017 D-5 and the gate's numbers.
Implemented locally as an offline evaluation only. The application is unchanged: every citation
still says `support: "not_verified"` ("Retrieved source — support not verified").

## Context

A citation marker today proves only that the cited source was retrieved for the question (ADR 017,
D-5). A model can cite a real source for a sentence the source does not say. M10 decision 6 forbids
showing "Supported" until a claim-level check has been shown, on an evaluation set, to be reliable
enough. No such set or measurement existed.

## Decision (proposed)

1. **Measure before labelling.** `app/evaluation/evidence.py` evaluates a checker on labelled
   claims: `supported` (the passage states it), `unsupported` (it does not), and `conflicting` (it
   states something incompatible). `scripts/evaluate_evidence.py` prints the report. Nothing in
   the request path imports the module (a unit test enforces this).
2. **The unit of judgement** is one cited sentence against the exact passage the model received
   (`split_claims`; the passage is rebuilt and hash-checked as in ADR 018).
3. **The dangerous error comes first.** Calling an unsupported or conflicting claim "Supported" is
   worse than missing a supported one. The report leads with supported precision and the false
   "supported" rates per label.
4. **A gate, not a switch** (`SupportLabelGate`). The proposed criteria:

   | Criterion | Proposed value |
   |---|---|
   | Cases in total | at least 300 |
   | Cases per label | at least 100 |
   | Supported precision | at least 0.95 |
   | False "supported" on conflicting claims | at most 0.02 |
   | False "supported" on unsupported claims | at most 0.05 |
   | Owner approval | required (`owner_approved`, False in code) |

   Passing the gate would permit a separate, reviewed change to show a support label. It never
   turns one on by itself.
5. **The baseline is a floor.** `LexicalSupportChecker` (one sentence must cover at least 75% of
   the claim's content words, include all of its numbers, and agree with it on negation) makes no
   model call. It shows what a cheap check misses; it is not a candidate for release.

## Current measurement (2026-11-04, local)

Dataset v1 (`backend/tests/evaluation/data/evidence_eval_dataset.json`): **42 synthetic claims**
written by hand by the coding assistant over six invented policy passages (18 supported,
11 unsupported, 13 conflicting). It includes cases built to defeat word overlap. It is not drawn
from real documents or real model answers and is far below the gate's size.

| Metric (lexical baseline) | Value |
|---|---|
| Accuracy | 0.833 (35 / 42) |
| Supported precision | 0.789 (15 / 19) |
| Supported recall | 0.833 (15 / 18) |
| False "supported" on unsupported | 0.091 (1 / 11) |
| False "supported" on conflicting | 0.231 (3 / 13) |
| Gate | **FAIL** on every criterion |

Its errors: number words it does not compare ("five" vs "three", "ten" vs "seven"), a changed
qualifier ("calendar" vs "working" days), a changed unit ("week" vs "month"), and paraphrases it
cannot match ("needs HR approval", "you have 30 days") or that add words ("Taking sick leave …
your …"). That is 7 errors: 4 wrongly called supported (d4, r4, e7, d6) and 3 supported claims
missed (t3, r2, l3). The checker was **not** tuned to this set.

## Options for a real checker (for D-5)

| Option | Cost | Failure modes |
|---|---|---|
| Lexical rules (the baseline) | none | paraphrase, number words, swapped roles, recombined facts |
| A local NLI (entailment) model | CPU time per claim; a new model download and dependency | domain shift, long passages, numbers; needs its own evaluation |
| An LLM judge (the existing gateway) | one billed call per answer, added latency | inconsistency between runs, prompt injection from the passage, cost |

Any option needs a larger set first, ideally including real (consented, non-sensitive) answers
and passages, with labels checked by a second person.

## Consequences

- Answers keep "Retrieved source — support not verified."
- The evaluation can be re-run offline at any time, and the unit tests pin the current numbers, so
  a change to the checker or the set is visible in review.
- Not done: a larger or real dataset; an NLI or LLM checker; any user-facing support label.
