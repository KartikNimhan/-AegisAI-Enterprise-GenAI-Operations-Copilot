"""A2A task-URL validation edge cases (M12 review findings L1-L3).

The Agent Card's task URL is remote-supplied. It is accepted only in one
canonical form, so `urllib` and `httpx` cannot disagree about where a request
(or the caller's bearer token) would go. Every rejection happens BEFORE any
request is made, as an `A2AInvalidCardError` — never a raw `ValueError`.
"""

from __future__ import annotations

import httpx
import pytest

from app.a2a.agent_card import agent_card_to_json_dict, build_research_agent_card
from app.a2a.client import A2AClient
from app.a2a.exceptions import A2AConnectionError, A2AInvalidCardError, A2AUntrustedAgentError

from .test_a2a_client import _BASE_URL, _card_response, _install_transport, _settings
from .test_a2a_client_auth import TOKEN, _card_with_task_url, _recording_handler

GOOD_PATH = "/api/v1/agents/research/tasks"


@pytest.mark.parametrize(
    "task_url",
    [
        # dot-segment traversal (httpx normalizes ".." — it would reach /api/v1/documents)
        f"{_BASE_URL}/api/v1/agents/../documents",
        f"{_BASE_URL}/api/v1/agents/research/../../documents",
        f"{_BASE_URL}/api/v1/agents/./research/tasks",
        f"{_BASE_URL}/api/v1/agents/research/tasks/..",
        # percent-encoded dots, slashes and backslashes (including double encoding)
        f"{_BASE_URL}/api/v1/agents/%2e%2e/documents",
        f"{_BASE_URL}/api/v1/agents/%2E%2E/documents",
        f"{_BASE_URL}/api/v1/agents/research%2ftasks",
        f"{_BASE_URL}/api/v1/agents/research%5ctasks",
        f"{_BASE_URL}/api/v1/agents/%252e%252e/documents",
        # path parameters and empty segments
        f"{_BASE_URL}/api/v1/agents/..;/documents",
        f"{_BASE_URL}{GOOD_PATH};jsessionid=1",
        f"{_BASE_URL}/api/v1/agents//research/tasks",
        f"{_BASE_URL}//api/v1/agents/research/tasks",
        # backslashes
        f"{_BASE_URL}\\@evil.example/api/v1/agents/research/tasks",
        "http://evil.example\\@localhost:8000/api/v1/agents/research/tasks",
        f"{_BASE_URL}\\.evil.example/api/v1/agents/research/tasks",
        f"{_BASE_URL}/api/v1/agents\\research/tasks",
        # whitespace and control characters (urllib strips tab/newline, httpx rejects them)
        f"{_BASE_URL}\t{GOOD_PATH}",
        f"loc\talhost:8000{GOOD_PATH}",
        f"{_BASE_URL}\n{GOOD_PATH}",
        f"{_BASE_URL}{GOOD_PATH}\r\n",
        f"{_BASE_URL}{GOOD_PATH} ",
        f"{_BASE_URL}{GOOD_PATH}\x00",
        f"{_BASE_URL}{GOOD_PATH}\x7f",
        # malformed or hostile ports
        f"http://localhost:99999{GOOD_PATH}",
        f"http://localhost:abc{GOOD_PATH}",
        f"http://localhost:-1{GOOD_PATH}",
        f"http://localhost:0{GOOD_PATH}",
        "http://localhost:8000:8000" + GOOD_PATH,
        # malformed IPv6 literals
        f"http://[::1{GOOD_PATH}",
        f"http://[::1]x:8000{GOOD_PATH}",
        "http://[::1]:8000" + GOOD_PATH,  # well-formed, but a different host than the trusted one
        # non-ASCII (homoglyph / IDNA tricks)
        f"http://localhóst:8000{GOOD_PATH}",
        f"http://ｌocalhost:8000{GOOD_PATH}",
        f"{_BASE_URL}/api/v1/agents/résearch/tasks",
        # query strings and fragments
        f"{_BASE_URL}{GOOD_PATH}?x=1",
        f"{_BASE_URL}{GOOD_PATH}#fragment",
        f"{_BASE_URL}{GOOD_PATH}?",
        # userinfo in every position
        f"http://@localhost:8000{GOOD_PATH}",
        f"http://user@localhost:8000{GOOD_PATH}",
        f"http://localhost:8000@evil.example{GOOD_PATH}",
        f"http://localhost@evil.example{GOOD_PATH}",
        # wrong shape of path
        f"{_BASE_URL}/api/v1/agents/research/card",
        f"{_BASE_URL}/api/v1/agents/research/tasks/extra",
        f"{_BASE_URL}/api/v1/agents/research",
        f"{_BASE_URL}/api/v1/agents//tasks",
        f"{_BASE_URL}/api/v1/agentsX/research/tasks",
        f"{_BASE_URL}/API/V1/agents/research/tasks",
        f"{_BASE_URL}/api/v1/documents",
        f"{_BASE_URL}/",
        _BASE_URL,
        # other origins / schemes
        f"http://localhost.:8000{GOOD_PATH}",
        f"http://127.0.0.1:8000{GOOD_PATH}",
        f"http://0:8000{GOOD_PATH}",
        f"https://localhost:8000{GOOD_PATH}",
        f"ftp://localhost:8000{GOOD_PATH}",
        f"//localhost:8000{GOOD_PATH}",
        f"javascript:alert(1){GOOD_PATH}",
        "",
    ],
)
async def test_a_non_canonical_or_foreign_task_url_is_rejected_before_anything_is_sent(
    monkeypatch: pytest.MonkeyPatch, task_url: str
) -> None:
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, _card_with_task_url(task_url)))
    client = A2AClient(settings=_settings(), auth_token=TOKEN)

    with pytest.raises(A2AInvalidCardError):  # never a raw ValueError / InvalidURL
        await client.submit_research_task(_BASE_URL, question="q")

    assert [r.method for r in requests] == ["GET"]  # only the unauthenticated card fetch
    assert all(TOKEN not in str(r.headers) for r in requests)


@pytest.mark.parametrize(
    "task_url",
    [
        f"{_BASE_URL}{GOOD_PATH}",
        "HTTP://LOCALHOST:8000/api/v1/agents/research/tasks",  # case-insensitive scheme/host
        f"{_BASE_URL}/api/v1/agents/my_agent-2/tasks",  # allowed name characters
    ],
)
async def test_a_canonical_task_url_on_the_trusted_origin_is_accepted_and_carries_the_token(
    monkeypatch: pytest.MonkeyPatch, task_url: str
) -> None:
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, _card_with_task_url(task_url)))

    await A2AClient(settings=_settings(), auth_token=TOKEN).submit_research_task(
        _BASE_URL, question="q"
    )

    task_request = requests[-1]
    assert task_request.method == "POST"
    assert (task_request.url.host, task_request.url.port) == ("localhost", 8000)
    assert task_request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_an_explicit_default_port_equals_the_implicit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(trusted_a2a_agents=["http://localhost"])
    card = agent_card_to_json_dict(build_research_agent_card(settings, base_url="http://localhost"))
    card["supportedInterfaces"][0]["url"] = f"http://localhost:80{GOOD_PATH}"
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, card))

    await A2AClient(settings=settings, auth_token=TOKEN).submit_research_task(
        "http://localhost", question="q"
    )

    assert requests[-1].method == "POST"


async def test_port_zero_is_never_treated_as_the_default_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(trusted_a2a_agents=["http://localhost:80"])
    card = agent_card_to_json_dict(
        build_research_agent_card(settings, base_url="http://localhost:80")
    )
    card["supportedInterfaces"][0]["url"] = f"http://localhost:0{GOOD_PATH}"
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, card))

    with pytest.raises(A2AInvalidCardError):
        await A2AClient(settings=settings, auth_token=TOKEN).submit_research_task(
            "http://localhost:80", question="q"
        )

    assert [r.method for r in requests] == ["GET"]


async def test_the_path_prefix_follows_the_configured_api_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(api_v1_prefix="/v2")
    card = agent_card_to_json_dict(build_research_agent_card(settings, base_url=_BASE_URL))
    requests: list[httpx.Request] = []

    card["supportedInterfaces"][0]["url"] = f"{_BASE_URL}/v2/agents/research/tasks"
    _install_transport(monkeypatch, _recording_handler(requests, card))
    await A2AClient(settings=settings).submit_research_task(_BASE_URL, question="q")
    assert requests[-1].url.path == "/v2/agents/research/tasks"

    card["supportedInterfaces"][0]["url"] = f"{_BASE_URL}{GOOD_PATH}"  # the old prefix
    with pytest.raises(A2AInvalidCardError):
        await A2AClient(settings=settings).submit_research_task(_BASE_URL, question="q")


async def test_a_malformed_trusted_base_url_never_gets_the_token_or_crashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only reachable in local development (outside it the settings validator
    rejects such an entry at load time). Even with a transport that does not
    care about the port, the client refuses with a controlled A2A error."""
    bad = "http://localhost:99999"
    settings = _settings(trusted_a2a_agents=[bad])
    requests: list[httpx.Request] = []
    _install_transport(monkeypatch, _recording_handler(requests, _card_response(_settings())))

    with pytest.raises(A2AUntrustedAgentError):
        await A2AClient(settings=settings, auth_token=TOKEN).submit_research_task(bad, question="q")

    assert all(r.method == "GET" for r in requests)


async def test_an_invalid_url_error_while_fetching_the_card_is_a_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = "http://localhost:99999"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("simulated")  # what the real httpx raises for this URL

    _install_transport(monkeypatch, handler)

    with pytest.raises(A2AConnectionError):
        await A2AClient(settings=_settings(trusted_a2a_agents=[bad])).fetch_agent_card(bad)


async def test_an_invalid_url_error_from_the_http_layer_is_a_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            raise httpx.InvalidURL("simulated")
        return httpx.Response(200, json=_card_response(_settings()))

    _install_transport(monkeypatch, handler)

    with pytest.raises(A2AConnectionError):
        await A2AClient(settings=_settings(), auth_token=TOKEN).submit_research_task(
            _BASE_URL, question="q"
        )
