"""Opt-in integration test for the full multi-agent workflow against a
real `uvicorn` server on a real TCP socket — the same pattern
`test_a2a_live.py` uses for the single Research Agent, extended to the
full Research/Document/Analyst orchestration.

Two tiers:
  * `test_real_http_transport_*`: real sockets/HTTP through all three
    specialized agents, with the LLM/retrieval/document dependencies
    overridden to fakes — proves the whole orchestration wire path
    independent of Groq/Postgres being available. Opt-in only via
    `RUN_MULTI_AGENT_LIVE_INTEGRATION`.
  * `test_real_groq_model_*`: the same real server, but the LLM gateway is
    left as the real one. Additionally requires `GROQ_API_KEY`.

Run explicitly via:
    RUN_MULTI_AGENT_LIVE_INTEGRATION=1 uv run pytest -m multi_agent_integration -v
    RUN_MULTI_AGENT_LIVE_INTEGRATION=1 GROQ_API_KEY=sk-... \\
        uv run pytest -m multi_agent_integration -v
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import uvicorn

from app.a2a.document_agent import DocumentAgentService
from app.api.v1.document_agent import get_document_agent_service
from app.config import get_settings
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.schemas import CompletionResponse, TokenUsage
from app.main import app
from app.rag.retrieval.service import RetrievalService, get_retrieval_service

from ..unit.rag.doubles import FakeRetrievalStrategy, make_result
from ..unit.services.document_doubles import FakeDocumentRepository

pytestmark = [
    pytest.mark.multi_agent_integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_MULTI_AGENT_LIVE_INTEGRATION"),
        reason=(
            "RUN_MULTI_AGENT_LIVE_INTEGRATION is not set — skipping the real "
            "multi-agent HTTP transport test"
        ),
    ),
]


class _FakeGateway(LLMGateway):
    def __init__(self) -> None:
        pass

    async def chat_completion(self, **kwargs: object) -> CompletionResponse:
        return CompletionResponse(
            content="Synthesized final answer.", model="m", provider="test", usage=TokenUsage()
        )


def _fake_retrieval_with_evidence() -> RetrievalService:
    results = [make_result(content="Hotel costs are reimbursed up to policy limits.")]
    return RetrievalService(
        strategy=FakeRetrievalStrategy(results=results), settings=get_settings()
    )


def _make_document() -> Document:
    now = datetime.now(UTC)
    return Document(
        id=uuid.uuid4(),
        filename="internal.pdf",
        original_filename="Policy.pdf",
        content_type="application/pdf",
        document_type=DocumentType.PDF,
        file_size=10,
        checksum="a" * 64,
        status=DocumentStatus.PROCESSED,
        page_count=3,
        character_count=100,
        created_at=now,
        updated_at=now,
    )  # type: ignore[arg-type]


@pytest.fixture
async def live_server_base_url() -> AsyncIterator[str]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def test_real_http_transport_runs_a_full_workflow_with_fake_backends(
    live_server_base_url: str,
) -> None:
    document = _make_document()
    fake_documents = FakeDocumentRepository()
    fake_documents.documents[document.id] = document

    app.dependency_overrides[get_llm_gateway] = lambda: _FakeGateway()
    app.dependency_overrides[get_retrieval_service] = _fake_retrieval_with_evidence
    app.dependency_overrides[get_document_agent_service] = lambda: DocumentAgentService(
        documents=fake_documents  # type: ignore[arg-type]
    )
    get_settings.cache_clear()
    os.environ["TRUSTED_A2A_AGENTS"] = f'["{live_server_base_url}"]'
    get_settings.cache_clear()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{live_server_base_url}/api/v1/multi-agent/run",
                json={"message": (f"Compare the travel policy with document {document.id}.")},
            )
    finally:
        app.dependency_overrides.clear()
        os.environ.pop("TRUSTED_A2A_AGENTS", None)
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    agents_used = {a["agent_name"] for a in payload["agents_used"]}
    assert agents_used == {"research", "document", "analyst"}
    assert payload["answer"] == "Synthesized final answer."


@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY is not set — skipping the real Groq model call through multi-agent",
)
async def test_real_groq_model_through_the_full_multi_agent_stack(
    live_server_base_url: str,
) -> None:
    app.dependency_overrides[get_retrieval_service] = _fake_retrieval_with_evidence
    get_settings.cache_clear()
    os.environ["TRUSTED_A2A_AGENTS"] = f'["{live_server_base_url}"]'
    get_settings.cache_clear()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{live_server_base_url}/api/v1/multi-agent/run",
                json={"message": "What does our travel policy say about hotel reimbursement?"},
            )
    finally:
        app.dependency_overrides.clear()
        os.environ.pop("TRUSTED_A2A_AGENTS", None)
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["answer"].strip() != ""
