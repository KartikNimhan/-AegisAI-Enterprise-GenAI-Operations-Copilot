"""End-to-end integration tests: real HTTP + real PostgreSQL + real
pgvector similarity search (via the `search_knowledge_base` tool), with a
fake `EmbeddingProvider` (controlled query vector, no real model download)
and a scripted `LLMGateway` (no real Groq call, but deterministic
multi-step tool-calling behavior).

Mirrors tests/integration/test_rag_flow.py's structure, proving the
API -> AgentService -> LangGraph -> ToolRegistry -> RetrievalService ->
pgvector chain end to end, plus the calculator tool (no DB involvement)
and a knowledge-search-then-calculator multi-step run.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.session import get_session
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.chunk_embedding import EMBEDDING_DIMENSION, ChunkEmbedding
from app.domain.models.document_chunk import DocumentChunk
from app.embeddings.providers.local import get_local_embedding_provider
from app.llm.gateway import get_llm_gateway
from app.main import app

from ..unit.agents.doubles import (
    ScriptedAgentGateway,
    make_final_completion,
    make_multi_tool_call_completion,
    make_tool_call_completion,
)
from ..unit.services.embedding_doubles import FakeEmbeddingProvider

pytestmark = pytest.mark.integration

_FAKE_MODEL = "fake-model"
_FAKE_MODEL_VERSION = "1"


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


@pytest.fixture
async def seeded_document(db_session: AsyncSession) -> uuid.UUID:
    """One PROCESSED document with a single chunk embedded identically to
    the query vector the fake embedding provider will return."""
    document_repo = DocumentRepository(db_session)
    document = document_repo.new(
        filename=f"{uuid.uuid4()}.txt",
        original_filename="Travel Policy.pdf",
        content_type="application/pdf",
        document_type=DocumentType.PDF,
        file_size=100,
        checksum=uuid.uuid4().hex + uuid.uuid4().hex,
        status=DocumentStatus.PROCESSED,
    )
    await db_session.flush()

    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=document.id,
        chunk_index=0,
        content="Employees may claim travel expenses with a valid receipt.",
        character_count=58,
        metadata_={"page_number": 4},
    )
    db_session.add(chunk)
    await db_session.flush()

    await ChunkEmbeddingRepository(db_session).add_all(
        [
            ChunkEmbedding(
                id=uuid.uuid4(),
                document_chunk_id=chunk.id,
                embedding=_unit_vector(0),
                embedding_provider="local",
                embedding_model=_FAKE_MODEL,
                embedding_model_version=_FAKE_MODEL_VERSION,
                embedding_dimension=EMBEDDING_DIMENSION,
            )
        ]
    )
    return document.id


def _override_embedding_provider() -> None:
    app.dependency_overrides[get_local_embedding_provider] = lambda: FakeEmbeddingProvider(
        name="local",
        model_name=_FAKE_MODEL,
        model_version=_FAKE_MODEL_VERSION,
        dimension=EMBEDDING_DIMENSION,
        effects=[[_unit_vector(0)]],
    )


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_local_embedding_provider, None)
        app.dependency_overrides.pop(get_llm_gateway, None)


async def test_agent_answers_using_the_knowledge_base_tool(
    client: AsyncClient, seeded_document: uuid.UUID
) -> None:
    _override_embedding_provider()
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(
                tool_name="search_knowledge_base",
                arguments={"query": "Can I claim travel expenses?"},
            ),
            make_final_completion("Employees may claim travel expenses with a receipt."),
        ]
    )
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = await client.post(
        "/api/v1/agents/run", json={"message": "Can I claim travel expenses?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "travel expenses" in body["answer"]
    assert body["tool_usage"][0]["name"] == "search_knowledge_base"
    assert body["tool_usage"][0]["success_count"] == 1
    assert len(body["sources"]) == 1
    assert body["sources"][0]["filename"] == "Travel Policy.pdf"
    assert body["sources"][0]["page"] == 4


async def test_agent_answers_using_the_calculator_tool(client: AsyncClient) -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(
                tool_name="calculator", arguments={"expression": "250 * 0.18"}
            ),
            make_final_completion("250 * 0.18 is 45."),
        ]
    )
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = await client.post("/api/v1/agents/run", json={"message": "What is 250 * 0.18?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "45" in body["answer"]
    assert body["tool_usage"][0]["name"] == "calculator"
    assert body["tool_usage"][0]["success_count"] == 1
    assert body["sources"] == []


async def test_agent_multi_step_knowledge_search_then_calculator(
    client: AsyncClient, seeded_document: uuid.UUID
) -> None:
    _override_embedding_provider()
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(
                tool_name="search_knowledge_base", arguments={"query": "travel expense policy"}
            ),
            make_tool_call_completion(
                tool_name="calculator", arguments={"expression": "250 * 0.18"}
            ),
            make_final_completion("Per the travel policy, the reimbursable tax portion is 45."),
        ]
    )
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = await client.post(
        "/api/v1/agents/run",
        json={"message": "What's 18% tax on a $250 hotel expense per our travel policy?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["steps"] == 3
    tool_names = {t["name"] for t in body["tool_usage"]}
    assert tool_names == {"search_knowledge_base", "calculator"}
    assert len(body["sources"]) == 1


async def test_agent_multi_tool_calls_in_a_single_llm_turn(client: AsyncClient) -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_multi_tool_call_completion(
                calls=[
                    ("calculator", {"expression": "1 + 1"}),
                    ("calculator", {"expression": "2 + 2"}),
                ]
            ),
            make_final_completion("The results are 2 and 4."),
        ]
    )
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = await client.post("/api/v1/agents/run", json={"message": "Compute two sums"})

    assert response.status_code == 200
    body = response.json()
    assert body["tool_usage"][0]["call_count"] == 2


async def test_agent_tool_failure_still_produces_a_controlled_final_answer(
    client: AsyncClient,
) -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="calculator", arguments={"expression": "1/0"}),
            make_final_completion("I can't divide by zero."),
        ]
    )
    app.dependency_overrides[get_llm_gateway] = lambda: gateway

    response = await client.post("/api/v1/agents/run", json={"message": "What is 1/0?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["tool_usage"][0]["failure_count"] == 1
