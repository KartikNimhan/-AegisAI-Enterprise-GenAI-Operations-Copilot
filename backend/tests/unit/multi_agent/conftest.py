"""Shared fixtures for multi-agent orchestrator tests.

Tests drive the real `POST /api/v1/multi-agent/run` endpoint through an
async client bound to the real FastAPI app via `httpx.ASGITransport` —
the orchestrator's own `A2AClient` also makes real `httpx.AsyncClient`
calls (to `Settings.trusted_a2a_agents[0]`, i.e. this same app), so those
are routed through a *second*, separately patched `httpx.AsyncClient`
bound to the same ASGI transport, the same pattern
`tests/unit/a2a/test_a2a_client.py` uses via `MockTransport`, just
exercising the *real* Research/Document/Analyst endpoints end-to-end
rather than a hand-written response. No real socket, no real Groq/
Postgres — LLM, retrieval, and document dependencies are overridden with
fakes.

Both the outer (test -> multi-agent endpoint) and inner (orchestrator ->
Research/Document/Analyst endpoints) clients must be built from the
*same* captured real `httpx.AsyncClient` class, captured *before* it is
patched — `httpx` is one shared module object, so building the outer
client from `httpx.AsyncClient` *after* patching would otherwise call the
patched version right back (infinite self-reference).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

import app.a2a.client as a2a_client_module
from app.a2a.document_agent import DocumentAgentService
from app.api.v1.document_agent import get_document_agent_service
from app.config import get_settings
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.main import app
from app.rag.retrieval.service import RetrievalService, get_retrieval_service

from ..rag.doubles import FakeRetrievalStrategy
from ..services.document_doubles import FakeDocumentRepository


@pytest.fixture
def fake_documents() -> FakeDocumentRepository:
    return FakeDocumentRepository()


@pytest.fixture
def orchestrator_env(
    monkeypatch: pytest.MonkeyPatch, fake_documents: FakeDocumentRepository
) -> Iterator[dict]:
    """Yields a mutable `state` dict: set `state["gateway"]` to a scripted
    gateway double (e.g. `ScriptedRAGGateway`) and/or `state
    ["retrieval_results"]` to a list of `RetrievalResult`s before calling
    the endpoint. `fake_documents` (the `FakeDocumentRepository` instance
    this env wires in) can be seeded directly by the test."""
    state: dict = {"gateway": None, "retrieval_results": []}

    class _Gateway(LLMGateway):
        def __init__(self) -> None:
            pass

        async def chat_completion(self, **kwargs: object):
            return await state["gateway"].chat_completion(**kwargs)

    def _retrieval() -> RetrievalService:
        return RetrievalService(
            strategy=FakeRetrievalStrategy(results=state["retrieval_results"]),
            settings=get_settings(),
        )

    def _document_agent_service() -> DocumentAgentService:
        return DocumentAgentService(documents=fake_documents)  # type: ignore[arg-type]

    real_async_client = httpx.AsyncClient
    asgi_transport = httpx.ASGITransport(app=app)

    def _patched_async_client(*, timeout: float) -> httpx.AsyncClient:
        return real_async_client(transport=asgi_transport, timeout=timeout)

    monkeypatch.setattr(a2a_client_module.httpx, "AsyncClient", _patched_async_client)
    app.dependency_overrides[get_llm_gateway] = lambda: _Gateway()
    app.dependency_overrides[get_retrieval_service] = _retrieval
    app.dependency_overrides[get_document_agent_service] = _document_agent_service

    state["_real_async_client"] = real_async_client
    state["_asgi_transport"] = asgi_transport
    yield state

    app.dependency_overrides.clear()


@pytest.fixture
async def async_client(orchestrator_env: dict) -> AsyncIterator[httpx.AsyncClient]:
    real_async_client = orchestrator_env["_real_async_client"]
    transport = orchestrator_env["_asgi_transport"]
    async with real_async_client(transport=transport, base_url="http://localhost:8000") as client:
        yield client
