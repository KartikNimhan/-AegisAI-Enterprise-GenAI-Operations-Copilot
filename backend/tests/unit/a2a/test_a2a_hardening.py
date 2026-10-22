"""A2A client boundary: malformed, oversized and slow responses, and what an error may reveal.

All traffic goes through `httpx.MockTransport`; nothing touches a network.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

import app.multi_agent.orchestrator as orchestrator_module
from app.a2a.client import A2AClient, parse_research_result, validate_task_shape
from app.a2a.exceptions import (
    A2AConnectionError,
    A2AInvalidCardError,
    A2AResponseError,
    A2ATimeoutError,
)
from app.multi_agent.adapters import client_facing_error
from app.multi_agent.models import STATUS_COMPLETED, STATUS_FAILED, AgentResult
from app.multi_agent.orchestrator import MultiAgentOrchestrator

from ..multi_agent.test_retry_and_limits import _FakeGateway
from .test_a2a_client import _BASE_URL, _card_response, _install_transport, _settings

COMPLETED = "TASK_STATE_COMPLETED"


def _client(monkeypatch: pytest.MonkeyPatch, handler, **settings: object) -> A2AClient:
    _install_transport(monkeypatch, handler)
    return A2AClient(settings=_settings(**settings))


def _serve(card: httpx.Response | None = None, task: httpx.Response | None = None, **settings):
    resolved = _settings(**settings)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/agent-card.json"):
            return card or httpx.Response(200, json=_card_response(resolved))
        return task or httpx.Response(200, json={})

    return handler


# -- malformed JSON and shapes --------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>not json</html>"),
        httpx.Response(200, content=b"\xff\xfe\x00 not utf-8"),
        httpx.Response(200, json=["a", "list"]),
        httpx.Response(200, json="a string"),
        httpx.Response(200, content=b""),
    ],
)
async def test_a_malformed_agent_card_is_a_typed_error(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    client = _client(monkeypatch, _serve(card=response))

    with pytest.raises(A2AInvalidCardError):
        await client.fetch_agent_card(_BASE_URL)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=["list"]),
        httpx.Response(200, json={"status": "done"}),
        httpx.Response(200, json={"status": {"state": 7}}),
        httpx.Response(200, json={"status": {"state": COMPLETED}, "artifacts": "x"}),
        httpx.Response(200, json={"status": {"state": COMPLETED}, "artifacts": ["x"]}),
        httpx.Response(
            200, json={"status": {"state": COMPLETED}, "artifacts": [{"parts": "nope"}]}
        ),
        httpx.Response(
            200, json={"status": {"state": "X", "message": {"parts": ["text"]}}, "artifacts": []}
        ),
    ],
)
async def test_a_malformed_task_response_is_a_typed_error(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    client = _client(monkeypatch, _serve(task=response))

    with pytest.raises(A2AResponseError):
        await client.submit_research_task(_BASE_URL, question="q")


def _completed(sources: object) -> dict:
    return {
        "status": {"state": COMPLETED},
        "artifacts": [{"parts": [{"data": {"answer": "a", "sources": sources}}]}],
    }


@pytest.mark.parametrize(
    "sources",
    [
        [{"chunk_id": "not-a-uuid", "document_id": str(uuid.uuid4()), "filename": "f"}],
        [{}],
        ["not-an-object"],
        [
            {
                "chunk_id": str(uuid.uuid4()),
                "document_id": str(uuid.uuid4()),
                "filename": "f",
                "page_number": "abc",
            }
        ],
        "not-a-list",
    ],
)
def test_malformed_research_sources_are_a_typed_error(sources: object) -> None:
    with pytest.raises(A2AResponseError):
        parse_research_result(_completed(sources))


def test_a_well_formed_task_still_parses() -> None:
    source = {
        "chunk_id": str(uuid.uuid4()),
        "document_id": str(uuid.uuid4()),
        "filename": "f.pdf",
        "page_number": 2.0,
    }
    result = parse_research_result(_completed([source]))
    assert result.status == "completed" and result.sources[0].page_number == 2
    assert validate_task_shape({"status": {"state": COMPLETED}})


# -- size limits ----------------------------------------------------------------------------


async def test_a_body_over_the_cap_is_refused_and_not_fully_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumed = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal consumed
        for _ in range(10_000):
            consumed += 1
            yield b"A" * 1024

    client = _client(
        monkeypatch,
        _serve(task=httpx.Response(200, content=chunks())),
        a2a_max_response_bytes=4096,
    )

    with pytest.raises(A2AResponseError, match="larger than"):
        await client.submit_research_task(_BASE_URL, question="q")

    assert consumed < 20  # stopped early; the remaining ~10 MB was never pulled


async def test_a_declared_length_over_the_cap_is_refused_before_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(200, content=b"{}", headers={"content-length": "999999"})
    client = _client(monkeypatch, _serve(card=response), a2a_max_response_bytes=4096)

    with pytest.raises(A2AInvalidCardError, match="larger than"):
        await client.fetch_agent_card(_BASE_URL)


@pytest.mark.parametrize("declared", ["abc", "-5", "1e3", ""])
async def test_an_invalid_content_length_is_refused(
    monkeypatch: pytest.MonkeyPatch, declared: str
) -> None:
    response = httpx.Response(200, content=b"{}", headers={"content-length": declared})
    client = _client(monkeypatch, _serve(task=response))

    with pytest.raises(A2AResponseError):
        await client.submit_research_task(_BASE_URL, question="q")


async def test_a_card_over_the_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    big = httpx.Response(200, content=b'{"name":"' + b"A" * 50_000 + b'"}')
    client = _client(monkeypatch, _serve(card=big), a2a_max_response_bytes=4096)

    with pytest.raises(A2AInvalidCardError, match="larger than"):
        await client.fetch_agent_card(_BASE_URL)


# -- deadlines ------------------------------------------------------------------------------


async def test_a_slow_drip_response_hits_the_overall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def drip() -> AsyncIterator[bytes]:
        yield b'{"status": '
        for _ in range(200):  # each gap is far under the per-phase timeout
            await asyncio.sleep(0.05)
            yield b" "

    client = _client(
        monkeypatch,
        _serve(task=httpx.Response(200, content=drip())),
        a2a_client_timeout_seconds=5.0,
        a2a_total_timeout_seconds=0.3,
    )

    with pytest.raises(A2ATimeoutError):
        await client.submit_research_task(_BASE_URL, question="q")


def test_the_new_limits_are_validated() -> None:
    for bad in ({"a2a_max_response_bytes": 10}, {"a2a_total_timeout_seconds": 0}):
        with pytest.raises(ValueError):
            _settings(**bad)


# -- nothing sensitive leaves the client -----------------------------------------------------


async def test_connection_errors_do_not_carry_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect to 10.1.2.3:9999 refused (secret-host.internal)")

    client = _client(monkeypatch, handler)

    with pytest.raises(A2AConnectionError) as raised:
        await client.fetch_agent_card(_BASE_URL)

    assert "10.1.2.3" not in str(raised.value) and "secret-host" not in str(raised.value)


async def test_a_remote_failure_message_is_not_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.a2a.exceptions import A2ATaskFailedError

    task = {
        "status": {
            "state": "TASK_STATE_FAILED",
            "message": {"parts": [{"text": "db password is hunter2 at db.internal:5432"}]},
        }
    }
    client = _client(monkeypatch, _serve(task=httpx.Response(200, json=task)))

    with pytest.raises(A2ATaskFailedError) as raised:
        await client.submit_research_task(_BASE_URL, question="q")

    assert "hunter2" not in str(raised.value)


def test_client_facing_errors_are_fixed_text() -> None:
    leaky = A2AConnectionError("could not reach http://10.0.0.5:8000: boom")
    assert "10.0.0.5" not in client_facing_error(leaky)
    assert client_facing_error(ValueError("raw detail")) == (
        "The agent could not complete the task."
    )


# -- one failing agent does not fail the workflow ---------------------------------------------


def _ok(name: str) -> AgentResult:
    return AgentResult(
        agent_name=name,
        capability="x",
        task_id="t",
        status=STATUS_COMPLETED,
        answer=f"{name} answer",
    )


async def test_an_unexpected_adapter_exception_fails_only_that_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.multi_agent.router import RoutingDecision

    monkeypatch.setattr(
        orchestrator_module,
        "route",
        lambda message: RoutingDecision(
            capabilities=("research", "document_analysis"), document_ids=[uuid.uuid4()]
        ),
    )
    finished: list[str] = []

    async def research(*, client, settings, context):
        await asyncio.sleep(0.05)
        finished.append("research")
        return _ok("research")

    async def document(*, client, settings, context):
        raise KeyError("http://10.0.0.5:8000 /secret")

    monkeypatch.setitem(orchestrator_module._ADAPTER_BY_AGENT, "research", research)
    monkeypatch.setitem(orchestrator_module._ADAPTER_BY_AGENT, "document", document)
    settings = _settings(multi_agent_timeout_seconds=5.0, multi_agent_agent_timeout_seconds=5.0)
    orchestrator = MultiAgentOrchestrator(
        settings=settings, gateway=_FakeGateway(), a2a_client=A2AClient(settings=settings)
    )

    result = await orchestrator.run(question="research and analyze the document")

    by_agent = {r.agent_name: r for r in result.agent_results}
    assert by_agent["research"].status == STATUS_COMPLETED
    assert by_agent["document"].status == STATUS_FAILED
    assert "10.0.0.5" not in (by_agent["document"].error or "")
    assert finished == ["research"]  # the sibling was allowed to finish, not orphaned
