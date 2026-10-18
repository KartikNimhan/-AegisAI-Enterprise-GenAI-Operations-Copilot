"""A2A token forwarding and task-URL validation (Milestone 12).

The Agent Card is remote-supplied data: its task URL must be proven to point
at the trusted agent BEFORE anything (payload or bearer token) is sent to it.
All against a mocked HTTP transport — no real network.
"""

from __future__ import annotations

import httpx
import pytest

import app.a2a.client as client_module
from app.a2a.client import A2AClient
from app.a2a.exceptions import A2AConnectionError, A2AInvalidCardError
from app.a2a.schemas import ResearchResult
from app.a2a.tasks import build_task, task_to_dict

from .test_a2a_client import _BASE_URL, _card_response, _install_transport, _settings

TOKEN = "super-secret-bearer-token-value"


def _task_payload() -> dict:
    return task_to_dict(
        build_task(question="q", result=ResearchResult(status="completed", answer="ok", sources=[]))
    )


def _recording_handler(requests: list[httpx.Request], card: dict, *, task_response=None):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/.well-known/agent-card.json"):
            return httpx.Response(200, json=card)
        if task_response is not None:
            return task_response(request)
        return httpx.Response(200, json=_task_payload())

    return handler


def _card_with_task_url(url: object) -> dict:
    card = _card_response(_settings())
    card["supportedInterfaces"][0]["url"] = url
    return card


async def test_the_task_post_carries_the_bearer_token_but_the_card_fetch_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, _card_response(_settings())))
    client = A2AClient(settings=_settings(), auth_token=TOKEN)

    result = await client.submit_research_task(_BASE_URL, question="q")

    assert result.status == "completed"
    card_request, task_request = requests
    assert card_request.method == "GET"
    assert "authorization" not in card_request.headers
    assert task_request.method == "POST"
    assert task_request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_no_authorization_header_is_sent_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, _card_response(_settings())))

    await A2AClient(settings=_settings()).submit_research_task(_BASE_URL, question="q")

    assert all("authorization" not in r.headers for r in requests)


@pytest.mark.parametrize(
    "task_url",
    [
        "http://evil.example.test/api/v1/agents/research/tasks",  # different host
        "http://localhost:9999/api/v1/agents/research/tasks",  # same host, other port
        "https://localhost:8000/api/v1/agents/research/tasks",  # other scheme
        "http://localhost:8000/admin/tasks",  # right origin, outside the agents path
        "http://localhost:8000/api/v1/documents",  # right origin, a different API area
        "http://user:pw@localhost:8000/api/v1/agents/research/tasks",  # embedded credentials
        "http://localhost.evil.example.test:8000/api/v1/agents/research/tasks",  # look-alike host
        "/api/v1/agents/research/tasks",  # relative URL: no origin to prove
    ],
)
async def test_a_task_url_outside_the_trusted_origin_is_rejected_before_anything_is_sent(
    monkeypatch: pytest.MonkeyPatch, task_url: str
) -> None:
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, _card_with_task_url(task_url)))
    client = A2AClient(settings=_settings(), auth_token=TOKEN)

    with pytest.raises(A2AInvalidCardError):
        await client.submit_research_task(_BASE_URL, question="q")

    # Only the (unauthenticated) card fetch happened: no task POST, no token sent.
    assert [r.method for r in requests] == ["GET"]
    assert all(TOKEN not in str(r.headers) for r in requests)


@pytest.mark.parametrize("bad", [123, None, ["http://localhost:8000/api/v1/agents/x"], {}])
async def test_a_card_whose_task_url_is_not_a_string_is_rejected(
    monkeypatch: pytest.MonkeyPatch, bad: object
) -> None:
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, _card_with_task_url(bad)))

    with pytest.raises(A2AInvalidCardError):
        await A2AClient(settings=_settings(), auth_token=TOKEN).submit_research_task(
            _BASE_URL, question="q"
        )

    assert [r.method for r in requests] == ["GET"]


async def test_a_redirect_from_the_task_endpoint_is_not_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trusted agent that redirects must not cause the token to follow."""
    requests: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://evil.example.test/steal"})

    _install_transport(
        monkeypatch,
        _recording_handler(requests, _card_response(_settings()), task_response=redirect),
    )
    client = A2AClient(settings=_settings(), auth_token=TOKEN)

    with pytest.raises(A2AConnectionError):
        await client.submit_research_task(_BASE_URL, question="q")

    assert [r.method for r in requests] == ["GET", "POST"]
    assert all(r.url.host != "evil.example.test" for r in requests)


async def test_the_token_is_never_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    class _Recorder:
        def __getattr__(self, level: str):
            return lambda event, **kw: calls.append((event, kw))

    monkeypatch.setattr(client_module, "logger", _Recorder())
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, _card_response(_settings())))

    await A2AClient(settings=_settings(), auth_token=TOKEN).submit_research_task(
        _BASE_URL, question="q"
    )

    assert calls
    assert TOKEN not in repr(calls)
