"""Unit tests for RetrievalService: limit resolution and threshold
filtering against a fake strategy — no real database or model."""

from __future__ import annotations

import uuid

from app.config import Settings
from app.rag.retrieval.service import RetrievalService

from .doubles import FakeRetrievalStrategy, make_result


def make_settings(
    *, rag_top_k: int = 5, rag_max_results: int = 20, rag_similarity_threshold: float = 0.3
) -> Settings:
    return Settings(
        rag_top_k=rag_top_k,
        rag_max_results=rag_max_results,
        rag_similarity_threshold=rag_similarity_threshold,
    )


async def test_uses_configured_default_top_k_when_not_overridden() -> None:
    strategy = FakeRetrievalStrategy(results=[make_result()])
    service = RetrievalService(strategy=strategy, settings=make_settings(rag_top_k=7))

    await service.retrieve(query="hello")

    assert strategy.calls[0]["top_k"] == 7


async def test_caller_supplied_top_k_is_honored_within_the_ceiling() -> None:
    strategy = FakeRetrievalStrategy(results=[make_result()])
    service = RetrievalService(
        strategy=strategy, settings=make_settings(rag_top_k=5, rag_max_results=20)
    )

    await service.retrieve(query="hello", top_k=3)

    assert strategy.calls[0]["top_k"] == 3


async def test_caller_supplied_top_k_is_clamped_to_the_configured_ceiling() -> None:
    strategy = FakeRetrievalStrategy(results=[make_result()])
    service = RetrievalService(
        strategy=strategy, settings=make_settings(rag_top_k=5, rag_max_results=10)
    )

    await service.retrieve(query="hello", top_k=1000)

    assert strategy.calls[0]["top_k"] == 10


async def test_default_top_k_is_also_clamped_to_the_ceiling() -> None:
    strategy = FakeRetrievalStrategy(results=[make_result()])
    service = RetrievalService(
        strategy=strategy, settings=make_settings(rag_top_k=50, rag_max_results=10)
    )

    await service.retrieve(query="hello")

    assert strategy.calls[0]["top_k"] == 10


async def test_document_id_filter_is_forwarded_to_the_strategy() -> None:
    strategy = FakeRetrievalStrategy(results=[])
    service = RetrievalService(strategy=strategy, settings=make_settings())
    document_id = uuid.uuid4()

    await service.retrieve(query="hello", document_id=document_id)

    assert strategy.calls[0]["document_id"] == document_id


async def test_results_below_the_similarity_threshold_are_excluded() -> None:
    strong = make_result(content="strong match", distance=0.1)  # similarity 0.9
    weak = make_result(content="weak match", distance=0.9)  # similarity 0.1
    strategy = FakeRetrievalStrategy(results=[strong, weak])
    service = RetrievalService(
        strategy=strategy, settings=make_settings(rag_similarity_threshold=0.5)
    )

    outcome = await service.retrieve(query="hello")

    assert outcome.candidates == [strong, weak]  # candidates are unfiltered
    assert outcome.results == [strong]  # only the qualifying one remains


async def test_caller_supplied_threshold_overrides_the_configured_default() -> None:
    weak = make_result(distance=0.9)  # similarity 0.1
    strategy = FakeRetrievalStrategy(results=[weak])
    service = RetrievalService(
        strategy=strategy, settings=make_settings(rag_similarity_threshold=0.9)
    )

    outcome = await service.retrieve(query="hello", similarity_threshold=0.05)

    assert outcome.results == [weak]


async def test_no_qualifying_results_returns_empty_results_list() -> None:
    strategy = FakeRetrievalStrategy(results=[make_result(distance=1.5)])  # similarity -0.5
    service = RetrievalService(
        strategy=strategy, settings=make_settings(rag_similarity_threshold=0.3)
    )

    outcome = await service.retrieve(query="hello")

    assert outcome.results == []
    assert len(outcome.candidates) == 1


async def test_outcome_reports_the_embedding_model_used() -> None:
    strategy = FakeRetrievalStrategy(
        results=[], embedding_provider="local", embedding_model="m", embedding_model_version="2"
    )
    service = RetrievalService(strategy=strategy, settings=make_settings())

    outcome = await service.retrieve(query="hello")

    assert outcome.embedding_provider == "local"
    assert outcome.embedding_model == "m"
    assert outcome.embedding_model_version == "2"
