"""Opt-in integration test against the real A2A HTTP transport.

Runs the actual FastAPI app behind a real `uvicorn` server bound to a real
TCP socket on localhost (not `httpx.ASGITransport`/in-process, and not a
mocked transport the way tests/unit/a2a/ and
tests/unit/agents/test_agent_mcp_a2a_integration.py exercise the A2A
boundary) and drives it with the real `A2AClient` — proving the whole
wire path (TCP, HTTP, JSON, protobuf (de)serialization) actually works,
not just the application code above it.

Two tiers:
  * `test_real_http_transport_*`: real sockets/HTTP, but with the LLM
    gateway and retrieval strategy dependency-overridden to fakes — proves
    the transport, independent of Groq/Postgres being available. Opt-in
    only via `RUN_A2A_LIVE_INTEGRATION` (no DB/model dependency, but still
    a real subprocess-free server + extra sockets, so never on by default).
  * `test_real_groq_model_*`: the same real server, but the LLM gateway is
    left as the real one — exercises a genuine Groq call end-to-end
    through the full A2A stack. Additionally requires `GROQ_API_KEY`.

Run explicitly via:
    RUN_A2A_LIVE_INTEGRATION=1 uv run pytest -m a2a_integration -v
    RUN_A2A_LIVE_INTEGRATION=1 GROQ_API_KEY=sk-... uv run pytest -m a2a_integration -v
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import uvicorn

from app.a2a.client import A2AClient
from app.config import Settings, get_settings
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.schemas import CompletionResponse, TokenUsage
from app.main import app
from app.rag.retrieval.service import RetrievalService, get_retrieval_service

from ..unit.rag.doubles import FakeRetrievalStrategy, make_result

pytestmark = [
    pytest.mark.a2a_integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_A2A_LIVE_INTEGRATION"),
        reason="RUN_A2A_LIVE_INTEGRATION is not set — skipping the real A2A HTTP transport test",
    ),
]


class _FakeGateway(LLMGateway):
    def __init__(self) -> None:
        pass

    async def chat_completion(self, **kwargs: object) -> CompletionResponse:
        return CompletionResponse(
            content="Synthesized research answer.", model="m", provider="test", usage=TokenUsage()
        )


def _fake_retrieval_with_no_results() -> RetrievalService:
    return RetrievalService(strategy=FakeRetrievalStrategy(results=[]), settings=get_settings())


def _fake_retrieval_with_evidence() -> RetrievalService:
    results = [make_result(content="Paris is the capital and largest city of France.")]
    return RetrievalService(
        strategy=FakeRetrievalStrategy(results=results), settings=get_settings()
    )


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


def _trusting_settings(base_url: str) -> Settings:
    return Settings(trusted_a2a_agents=[base_url])  # type: ignore[arg-type]


async def test_real_http_transport_fetches_the_agent_card(live_server_base_url: str) -> None:
    client = A2AClient(settings=_trusting_settings(live_server_base_url))

    card = await client.fetch_agent_card(live_server_base_url)

    assert card["name"] == get_settings().research_agent_name


async def test_real_http_transport_submits_a_task_with_fake_backends(
    live_server_base_url: str,
) -> None:
    app.dependency_overrides[get_llm_gateway] = lambda: _FakeGateway()
    app.dependency_overrides[get_retrieval_service] = _fake_retrieval_with_no_results
    try:
        client = A2AClient(settings=_trusting_settings(live_server_base_url))
        result = await client.submit_research_task(
            live_server_base_url, question="What is in the knowledge base?"
        )
    finally:
        app.dependency_overrides.clear()

    assert result.status == "completed"
    assert result.answer.strip() != ""


@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY is not set — skipping the real Groq model call through A2A",
)
async def test_real_groq_model_through_the_full_a2a_stack(live_server_base_url: str) -> None:
    app.dependency_overrides[get_retrieval_service] = _fake_retrieval_with_evidence
    try:
        client = A2AClient(settings=_trusting_settings(live_server_base_url))
        result = await client.submit_research_task(
            live_server_base_url, question="What is the capital of France?"
        )
    finally:
        app.dependency_overrides.clear()

    assert result.status == "completed"
    assert result.answer.strip() != ""
