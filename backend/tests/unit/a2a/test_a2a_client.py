"""Unit tests for `A2AClient`: the trusted-agent allowlist, Agent Card
fetch/validation, task submission/result parsing, and the distinct error
categories (untrusted, invalid card, connection, timeout, task failure) —
all against a mocked HTTP transport, no real network.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

import app.a2a.client as client_module
from app.a2a.agent_card import agent_card_to_json_dict, build_research_agent_card
from app.a2a.client import A2AClient
from app.a2a.exceptions import (
    A2AConnectionError,
    A2AInvalidCardError,
    A2ATaskFailedError,
    A2ATimeoutError,
    A2AUntrustedAgentError,
)
from app.a2a.schemas import ResearchResult, ResearchSource
from app.a2a.tasks import build_task
from app.config import Settings

_BASE_URL = "http://localhost:8000"


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "trusted_a2a_agents": [_BASE_URL],
        "research_agent_name": "AegisAI Research Agent",
        "a2a_client_timeout_seconds": 5.0,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Patches `httpx.AsyncClient` (a single shared module-level attribute,
    not copied per-import) to route through a `MockTransport` instead of a
    real socket. Must capture the *real* class before patching — `httpx` is
    the same module object everywhere, so `_factory` calling
    `httpx.AsyncClient(...)` after the patch would otherwise call itself."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _factory(*, timeout: float) -> httpx.AsyncClient:
        return real_async_client(transport=transport, timeout=timeout)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", _factory)


def _card_response(settings: Settings, **card_overrides: object) -> dict:
    card = build_research_agent_card(settings, base_url=_BASE_URL)
    payload = agent_card_to_json_dict(card)
    payload.update(card_overrides)
    return payload


# -- Trusted-agent allowlist -------------------------------------------------------


async def test_fetch_agent_card_rejects_an_untrusted_base_url() -> None:
    client = A2AClient(settings=_settings(trusted_a2a_agents=["http://other-host:9000"]))

    with pytest.raises(A2AUntrustedAgentError):
        await client.fetch_agent_card(_BASE_URL)


async def test_submit_research_task_rejects_an_untrusted_base_url() -> None:
    client = A2AClient(settings=_settings(trusted_a2a_agents=["http://other-host:9000"]))

    with pytest.raises(A2AUntrustedAgentError):
        await client.submit_research_task(_BASE_URL, question="q")


# -- fetch_agent_card ---------------------------------------------------------------


async def test_fetch_agent_card_succeeds_for_a_trusted_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    payload = _card_response(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=settings)

    card = await client.fetch_agent_card(_BASE_URL)

    assert card["name"] == settings.research_agent_name


async def test_fetch_agent_card_rejects_a_name_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    payload = _card_response(settings, name="Some Other Agent")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=settings)

    with pytest.raises(A2AInvalidCardError):
        await client.fetch_agent_card(_BASE_URL)


async def test_fetch_agent_card_rejects_a_card_missing_the_research_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    payload = _card_response(settings, skills=[])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=settings)

    with pytest.raises(A2AInvalidCardError):
        await client.fetch_agent_card(_BASE_URL)


async def test_fetch_agent_card_rejects_a_card_with_no_supported_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    payload = _card_response(settings, supportedInterfaces=[])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=settings)

    with pytest.raises(A2AInvalidCardError):
        await client.fetch_agent_card(_BASE_URL)


async def test_fetch_agent_card_wraps_a_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection failure", request=request)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=_settings())

    with pytest.raises(A2AConnectionError):
        await client.fetch_agent_card(_BASE_URL)


async def test_fetch_agent_card_wraps_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=_settings())

    with pytest.raises(A2ATimeoutError):
        await client.fetch_agent_card(_BASE_URL)


# -- submit_research_task ------------------------------------------------------------


async def test_submit_research_task_returns_a_parsed_result_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    card_payload = _card_response(settings)
    source = ResearchSource(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="policy.pdf",
        page_number=2,
        similarity=0.9,
    )
    task = build_task(
        question="q",
        result=ResearchResult(status="completed", answer="The answer.", sources=[source]),
    )
    from app.a2a.tasks import task_to_dict

    task_payload = task_to_dict(task)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/agent-card.json"):
            return httpx.Response(200, json=card_payload)
        return httpx.Response(200, json=task_payload)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=settings)

    result = await client.submit_research_task(_BASE_URL, question="What is the policy?")

    assert result.status == "completed"
    assert result.answer == "The answer."
    assert len(result.sources) == 1
    # Page number must round-trip as an int, not the float protobuf's
    # `Value` wire format produces (see `app.a2a.client`'s own comment).
    assert result.sources[0].page_number == 2
    assert isinstance(result.sources[0].page_number, int)


async def test_submit_research_task_raises_on_a_failed_remote_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    card_payload = _card_response(settings)
    task = build_task(
        question="q",
        result=ResearchResult(status="failed", answer="", error="The language model is down"),
    )
    from app.a2a.tasks import task_to_dict

    task_payload = task_to_dict(task)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/agent-card.json"):
            return httpx.Response(200, json=card_payload)
        return httpx.Response(200, json=task_payload)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=settings)

    with pytest.raises(A2ATaskFailedError, match="language model is down"):
        await client.submit_research_task(_BASE_URL, question="q")


async def test_submit_research_task_treats_a_malformed_response_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    card_payload = _card_response(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/agent-card.json"):
            return httpx.Response(200, json=card_payload)
        # A "completed" task with no artifacts at all — never trust the
        # shape blindly.
        return httpx.Response(200, json={"status": {"state": "TASK_STATE_COMPLETED"}})

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=settings)

    with pytest.raises(A2ATaskFailedError):
        await client.submit_research_task(_BASE_URL, question="q")


async def test_submit_research_task_wraps_a_timeout_on_the_task_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    card_payload = _card_response(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/agent-card.json"):
            return httpx.Response(200, json=card_payload)
        raise httpx.ReadTimeout("simulated timeout", request=request)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=settings)

    with pytest.raises(A2ATimeoutError):
        await client.submit_research_task(_BASE_URL, question="q")


async def test_submit_research_task_wraps_the_agent_being_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection failure", request=request)

    _install_transport(monkeypatch, handler)
    client = A2AClient(settings=_settings())

    with pytest.raises(A2AConnectionError):
        await client.submit_research_task(_BASE_URL, question="q")
