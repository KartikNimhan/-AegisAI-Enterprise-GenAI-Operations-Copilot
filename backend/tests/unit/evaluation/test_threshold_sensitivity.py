"""Deterministic coverage for M11 Phase 2 item 4: proving that the
evaluation framework's `context_inclusion_rate` is genuinely downstream
of `RetrievalService`'s real similarity-threshold filtering, not a
restatement of `recall_at_k` under a different name.

This drives the *actual* `RetrievalService.retrieve` against a
`FakeRetrievalStrategy` returning results on opposite sides of a
configured `rag_similarity_threshold` (the same doubles
`backend/tests/unit/rag/test_retrieval_service.py` already uses to test
the threshold filter itself) — no DB, no model, no network. An earlier
version of this coverage lived in test_metrics.py and only fed
hand-constructed id sets straight into the pure metric functions,
without ever calling `RetrievalService`; it claimed to prove threshold
sensitivity but didn't actually exercise the filtering logic. This file
replaces that with a test that does.

`RetrievalRepository.search` itself (what the real runner's
`recall_at_k` measures from) is a raw top-K query with no threshold
applied at all — `RetrievalService.retrieve`'s `outcome.candidates` is
the equivalent unfiltered view for this fake-strategy setup, and
`outcome.results` is the threshold-filtered view `context_inclusion_rate`
is measured from. See `app.evaluation.runner` for how the real runner
wires these two stages together.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.evaluation import metrics
from app.rag.retrieval.schemas import RetrievalResult
from app.rag.retrieval.service import RetrievalService

from ..rag.doubles import FakeRetrievalStrategy, make_result


def _make_settings(*, rag_similarity_threshold: float) -> Settings:
    return Settings(
        rag_top_k=5, rag_max_results=20, rag_similarity_threshold=rag_similarity_threshold
    )


def _chunk_ids(results: list[RetrievalResult]) -> set[str]:
    return {str(r.chunk_id) for r in results}


async def test_context_inclusion_rate_drops_below_recall_at_k_when_threshold_excludes_a_chunk() -> (
    None
):
    """Two relevant chunks: one strong match that clears the configured
    threshold, one weak match that doesn't. The raw candidate set (what
    recall_at_k measures) sees both; the threshold-filtered result set
    (what context_inclusion_rate measures) only keeps the strong one —
    driven by RetrievalService's real filtering, not a hand-picked set."""
    strong = make_result(content="strong match", distance=0.1)  # similarity 0.9
    weak = make_result(content="weak match", distance=0.9)  # similarity 0.1
    relevant = {str(strong.chunk_id), str(weak.chunk_id)}

    strategy = FakeRetrievalStrategy(results=[strong, weak])
    service = RetrievalService(
        strategy=strategy, settings=_make_settings(rag_similarity_threshold=0.5)
    )

    outcome = await service.retrieve(query="hello")

    # The threshold filter actually ran and actually excluded the weak
    # match — this is RetrievalService's own behavior, asserted
    # directly, not assumed.
    assert _chunk_ids(outcome.candidates) == relevant
    assert _chunk_ids(outcome.results) == {str(strong.chunk_id)}

    candidate_fraction = metrics.recall_fraction(_chunk_ids(outcome.candidates), relevant)
    result_fraction = metrics.recall_fraction(_chunk_ids(outcome.results), relevant)
    recall = metrics.recall_at_k([candidate_fraction])
    context = metrics.context_inclusion_rate([result_fraction])

    assert recall.value == pytest.approx(1.0)
    assert context.value == pytest.approx(0.5)


async def test_context_inclusion_rate_matches_recall_at_k_when_threshold_excludes_nothing() -> None:
    """Same two chunks, but a lenient enough threshold that both clear
    it — recall_at_k and context_inclusion_rate agree, since nothing was
    filtered between the two stages."""
    strong = make_result(content="strong match", distance=0.1)  # similarity 0.9
    also_ok = make_result(content="also fine", distance=0.3)  # similarity 0.7
    relevant = {str(strong.chunk_id), str(also_ok.chunk_id)}

    strategy = FakeRetrievalStrategy(results=[strong, also_ok])
    service = RetrievalService(
        strategy=strategy, settings=_make_settings(rag_similarity_threshold=0.5)
    )

    outcome = await service.retrieve(query="hello")

    assert _chunk_ids(outcome.results) == relevant

    candidate_fraction = metrics.recall_fraction(_chunk_ids(outcome.candidates), relevant)
    result_fraction = metrics.recall_fraction(_chunk_ids(outcome.results), relevant)
    recall = metrics.recall_at_k([candidate_fraction])
    context = metrics.context_inclusion_rate([result_fraction])

    assert recall.value == context.value == pytest.approx(1.0)


async def test_a_caller_supplied_threshold_override_changes_context_inclusion_rate() -> None:
    """RetrievalService.retrieve accepts a per-call similarity_threshold
    override (the same real parameter RAGService/the evaluation runner
    could pass) — proving context_inclusion_rate tracks *that*
    real-threshold value, not just the configured default."""
    weak = make_result(content="weak match", distance=0.9)  # similarity 0.1
    relevant = {str(weak.chunk_id)}
    strategy = FakeRetrievalStrategy(results=[weak])
    service = RetrievalService(
        strategy=strategy, settings=_make_settings(rag_similarity_threshold=0.9)
    )

    excluded = await service.retrieve(query="hello")
    included = await service.retrieve(query="hello", similarity_threshold=0.05)

    assert excluded.results == []
    assert _chunk_ids(included.results) == relevant

    context_excluded = metrics.context_inclusion_rate(
        [metrics.recall_fraction(_chunk_ids(excluded.results), relevant)]
    )
    context_included = metrics.context_inclusion_rate(
        [metrics.recall_fraction(_chunk_ids(included.results), relevant)]
    )

    assert context_excluded.value == pytest.approx(0.0)
    assert context_included.value == pytest.approx(1.0)
