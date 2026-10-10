"""Pure, deterministic metric functions — no I/O, no database, no model
call. Each metric that genuinely requires live infrastructure the caller
doesn't have available is represented by `MetricResult(status="skipped",
reason=...)` rather than a fabricated value; see this module's own
`SKIPPED_NO_LIVE_LLM` for the one metric Phase 1 explicitly cannot
compute (see scripts/evaluate.py's module docstring for why).
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


def recall_hit(retrieved_chunk_ids: set[str], relevant_chunk_ids: set[str]) -> bool:
    """True if any relevant chunk id is among the retrieved ids. Both sets
    must already be the *same kind* of id (either both dataset ids or
    both real database ids) — the caller is responsible for mapping
    synthetic dataset ids to the real retrieved ids before calling this;
    see app.evaluation.runner for where that mapping happens."""
    if not relevant_chunk_ids:
        # A case with no relevant chunks (e.g. "no evidence should exist
        # for this question") is trivially satisfied by retrieving
        # nothing relevant — there is nothing to recall.
        return True
    return bool(retrieved_chunk_ids & relevant_chunk_ids)


def recall_at_k(hits: list[bool]) -> MetricResult:
    if not hits:
        return MetricResult(name="recall_at_k", status="error", reason="no cases evaluated")
    return MetricResult(name="recall_at_k", status="computed", value=sum(hits) / len(hits))


def context_inclusion_rate(hits: list[bool]) -> MetricResult:
    """Fraction of cases where the relevant chunk survived both the
    similarity-threshold filter (RetrievalService) and the context
    char-budget truncation (ContextAssembler) — i.e. would actually have
    reached an LLM prompt, not just the raw top-K candidate set recall_at_k
    measures. See scripts/evaluate.py's docstring for why this is a
    distinct, real signal and not a restatement of recall_at_k."""
    if not hits:
        return MetricResult(
            name="context_inclusion_rate", status="error", reason="no cases evaluated"
        )
    return MetricResult(
        name="context_inclusion_rate", status="computed", value=sum(hits) / len(hits)
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


def skipped_metric(name: str, reason: str) -> MetricResult:
    return MetricResult(name=name, status="skipped", reason=reason)
