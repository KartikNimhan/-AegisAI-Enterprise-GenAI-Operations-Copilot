"""Unit tests for the search_knowledge_base tool: wraps RetrievalService
directly, never re-implements vector search."""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from app.agents.tools.base import ToolRegistry
from app.agents.tools.knowledge_base import KnowledgeBaseSearchArgs, build_knowledge_base_tool
from app.config import Settings
from app.rag.retrieval.service import RetrievalService

from ..rag.doubles import FakeRetrievalStrategy, make_result


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "rag_top_k": 5,
        "rag_max_results": 20,
        "rag_similarity_threshold": 0.3,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


async def test_successful_retrieval_returns_structured_results() -> None:
    strategy = FakeRetrievalStrategy(
        results=[make_result(content="Evidence here.", filename="Policy.pdf", page_number=4)]
    )
    retrieval = RetrievalService(strategy=strategy, settings=make_settings())
    tool = build_knowledge_base_tool(retrieval)

    result = await tool.executor(KnowledgeBaseSearchArgs(query="a question"))

    assert result.success is True
    assert result.data is not None
    assert len(result.data["results"]) == 1
    assert result.data["results"][0]["content"] == "Evidence here."
    assert result.data["results"][0]["filename"] == "Policy.pdf"
    assert result.data["results"][0]["page_number"] == 4
    assert "embedding" not in result.data["results"][0]


async def test_no_results_is_still_a_successful_empty_response() -> None:
    strategy = FakeRetrievalStrategy(results=[])
    retrieval = RetrievalService(strategy=strategy, settings=make_settings())
    tool = build_knowledge_base_tool(retrieval)

    result = await tool.executor(KnowledgeBaseSearchArgs(query="unanswerable"))

    assert result.success is True
    assert result.data == {"results": [], "message": "No relevant knowledge base content found."}


async def test_retrieval_failure_is_caught_by_the_registry_as_internal_error() -> None:
    class _BrokenStrategy(FakeRetrievalStrategy):
        async def search(self, **kwargs: object) -> list:  # type: ignore[override]
            raise RuntimeError("pgvector exploded")

    retrieval = RetrievalService(strategy=_BrokenStrategy(), settings=make_settings())
    tool = build_knowledge_base_tool(retrieval)

    registry = ToolRegistry()
    registry.register(tool)

    result = await registry.execute("search_knowledge_base", json.dumps({"query": "q"}))

    assert result.success is False
    assert result.error_code == "internal_error"
    assert "pgvector exploded" not in (result.error or "")


async def test_document_id_filter_is_forwarded() -> None:
    strategy = FakeRetrievalStrategy(results=[])
    retrieval = RetrievalService(strategy=strategy, settings=make_settings())
    tool = build_knowledge_base_tool(retrieval)
    document_id = uuid.uuid4()

    await tool.executor(KnowledgeBaseSearchArgs(query="q", document_id=document_id))

    assert strategy.calls[0]["document_id"] == document_id


def test_top_k_is_bounded_by_the_args_schema() -> None:
    with pytest.raises(ValidationError):
        KnowledgeBaseSearchArgs(query="q", top_k=1000)
