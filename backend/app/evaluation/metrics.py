"""Pure, deterministic metric functions — no I/O, no database, no model
call. Each metric that genuinely requires live infrastructure the caller
doesn't have available is represented by `MetricResult(status="skipped",
reason=...)` rather than a fabricated value; see this module's own
`SKIPPED_NO_LIVE_LLM` for the one kind Phase 1 explicitly cannot compute
(see scripts/evaluate.py's module docstring for why).

Phase 2 note on "no-answer" cases: a case can legitimately have no
relevant chunk at all (the corpus has no evidence for the question —
see `app.evaluation.dataset.EvalCase.expect_no_answer`). Such a case
must never be folded into `recall_at_k`/`context_inclusion_rate` — doing
so via a trivial "nothing to recall, so count it as a hit" rule would
silently inflate those metrics every time a no-answer case is added,
which is exactly backwards for a metric meant to catch retrieval
regressions. `recall_fraction` therefore refuses to accept an empty
`relevant_chunk_ids`; the runner excludes no-answer cases from the
recall/context-inclusion calculation entirely and reports on them
separately via `no_answer_abstention_rate`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MetricStatus = Literal["computed", "skipped", "error"]

SKIPPED_NO_LIVE_LLM = (
    "requires a live LLM call to generate a real answer to score — "
    "Phase 1 of the evaluation framework does not call any LLM "
    "(no API key requirement, no paid calls; see scripts/evaluate.py)"
)


@dataclass(frozen=True)
class MetricResult:
    name: str
    status: MetricStatus
    value: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status == "computed" and self.value is None:
            raise ValueError(f"metric {self.name!r} is 'computed' but has no value")
        if self.status in ("skipped", "error") and not self.reason:
            raise ValueError(f"metric {self.name!r} is {self.status!r} but has no reason")


def recall_fraction(retrieved_chunk_ids: set[str], relevant_chunk_ids: set[str]) -> float:
    """Fraction of `relevant_chunk_ids` present in `retrieved_chunk_ids`
    — the conventional recall definition (items found / items that
    matter), not just "was anything relevant found at all". For a case
    with exactly one relevant chunk this is 0.0 or 1.0, identical to a
    plain hit/no-hit measurement; it only starts to differ for a case
    with more than one relevant chunk, where partial retrieval becomes
    visible instead of collapsing to a single boolean.

    Both sets must already be the *same kind* of id (either both dataset
    ids or both real database ids) — the caller maps synthetic dataset
    ids to real retrieved ids before calling this; see
    `app.evaluation.runner`.

    Requires a non-empty `relevant_chunk_ids`. There is nothing to
    compute recall over for a case that intentionally has no relevant
    chunk (a "no-answer" case, see module docstring) — callers must
    exclude those cases before calling this and report on them
    separately via `no_answer_abstention_rate`.
    """
    if not relevant_chunk_ids:
        raise ValueError(
            "recall_fraction requires a non-empty relevant_chunk_ids set — "
            "exclude no-answer cases before calling this (see module docstring)"
        )
    found = retrieved_chunk_ids & relevant_chunk_ids
    return len(found) / len(relevant_chunk_ids)


def recall_at_k(fractions: list[float]) -> MetricResult:
    """Mean of per-case `recall_fraction` values, over cases that have at
    least one relevant chunk. No-answer cases must never be included in
    `fractions` — see `recall_fraction`."""
    if not fractions:
        return MetricResult(name="recall_at_k", status="error", reason="no cases evaluated")
    return MetricResult(
        name="recall_at_k", status="computed", value=sum(fractions) / len(fractions)
    )


def context_inclusion_rate(fractions: list[float]) -> MetricResult:
    """Mean, over the same cases `recall_at_k` covers, of the fraction of
    relevant chunks that survived both the similarity-threshold filter
    (RetrievalService) and the context char-budget truncation
    (ContextAssembler) — i.e. would actually have reached an LLM prompt,
    not just the raw top-K candidate set `recall_at_k` measures. See
    scripts/evaluate.py's docstring for why this is a distinct, real
    signal and not a restatement of recall_at_k."""
    if not fractions:
        return MetricResult(
            name="context_inclusion_rate", status="error", reason="no cases evaluated"
        )
    return MetricResult(
        name="context_inclusion_rate", status="computed", value=sum(fractions) / len(fractions)
    )


def operational_failure_rate(failure_count: int, total_count: int) -> MetricResult:
    if total_count == 0:
        return MetricResult(
            name="operational_failure_rate", status="error", reason="no cases evaluated"
        )
    return MetricResult(
        name="operational_failure_rate",
        status="computed",
        value=failure_count / total_count,
    )


def no_answer_abstention_rate(abstained: list[bool]) -> MetricResult:
    """Over cases marked `expect_no_answer=True` only: the fraction for
    which `RetrievalService.retrieve` (the real, configured similarity
    threshold) returned zero results — i.e. nothing cleared the
    production confidence threshold for that question. This reuses a
    real, already-production-meaningful signal (the same empty-results
    condition `ResearchAgentService` itself checks to decide whether to
    say "no relevant evidence was found" instead of calling the LLM), not
    a metric invented for this dataset.

    Limitation (document, don't oversell): this measures only whether
    the configured threshold happened to exclude everything for a given
    question against this small, topically well-separated synthetic
    corpus — it is not proof that the system "knows" it lacks an answer
    in any deeper sense, and a larger or more topically overlapping real
    corpus could behave very differently. See
    backend/tests/evaluation/README.md's no-answer-case section.

    `status="skipped"` (never "error") when the dataset has no
    `expect_no_answer` case at all — that is a normal, expected shape for
    a dataset version, not a failure.
    """
    if not abstained:
        return MetricResult(
            name="no_answer_abstention_rate",
            status="skipped",
            reason="the dataset has no case with expect_no_answer=true",
        )
    return MetricResult(
        name="no_answer_abstention_rate",
        status="computed",
        value=sum(abstained) / len(abstained),
    )


def citation_validity_rate(answers: list[tuple[int, int]]) -> MetricResult:
    """Over answers that contain at least one citation: the fraction of cited ids (counted per
    answer) that referred to a source that was really retrieved. `answers` holds
    `(valid_count, invalid_count)` per answer, e.g. from `app.rag.citations.sanitize_citations`.

    Unlike `citation_precision` this needs no judgement about whether a citation *supports* the
    claim, so it is deterministic and can be scored offline against scripted answers; it measures
    only the "no citation of evidence that was never provided" property. Answers with no citation
    are ignored (a lack of citations is a different failure); with none at all it is skipped.
    """
    scored = [(valid, invalid) for valid, invalid in answers if valid + invalid > 0]
    if not scored:
        return MetricResult(
            name="citation_validity_rate",
            status="skipped",
            reason="no answer contained a citation",
        )
    valid_total = sum(valid for valid, _ in scored)
    cited_total = sum(valid + invalid for valid, invalid in scored)
    return MetricResult(
        name="citation_validity_rate", status="computed", value=valid_total / cited_total
    )


def skipped_metric(name: str, reason: str) -> MetricResult:
    return MetricResult(name=name, status="skipped", reason=reason)
