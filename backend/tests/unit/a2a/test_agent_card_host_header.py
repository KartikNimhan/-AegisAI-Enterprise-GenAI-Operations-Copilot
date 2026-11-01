"""Public Agent Cards must not take their task URL from the request (AIGSEC-010).

The cards are served without authentication. Built from the request's Host (or a forwarded-host
header), a spoofed header, or a shared cache keyed without it, could hand a client a card whose
task endpoint is an attacker's server, and a client that trusts the card would send its task and
credentials there. The URL now comes from settings only.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app

CARDS = {
    "/.well-known/agent-card.json": "/api/v1/agents/research/tasks",
    "/api/v1/agents/research/card": "/api/v1/agents/research/tasks",
    "/api/v1/agents/document/card": "/api/v1/agents/document/tasks",
    "/api/v1/agents/analyst/card": "/api/v1/agents/analyst/tasks",
}
SPOOFED = {
    "Host": "attacker.example",
    "X-Forwarded-Host": "attacker.example",
    "X-Forwarded-Proto": "https",
    "Forwarded": "host=attacker.example;proto=https",
}


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def configure(**env: str) -> None:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield configure
    get_settings.cache_clear()


def _task_url(client: TestClient, path: str, headers: dict[str, str] | None = None) -> str:
    response = client.get(path, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()["supportedInterfaces"][0]["url"]


@pytest.mark.parametrize(("path", "task_path"), CARDS.items())
def test_spoofed_host_headers_do_not_change_the_card(
    client: TestClient, configured: Any, path: str, task_path: str
) -> None:
    configured()

    assert _task_url(client, path, SPOOFED) == f"http://localhost:8000{task_path}"


@pytest.mark.parametrize(("path", "task_path"), CARDS.items())
def test_a_configured_public_base_url_is_used(
    client: TestClient, configured: Any, path: str, task_path: str
) -> None:
    configured(A2A_PUBLIC_BASE_URL="http://127.0.0.1:18000")

    assert _task_url(client, path, SPOOFED) == f"http://127.0.0.1:18000{task_path}"


def test_without_a_public_url_the_first_trusted_agent_is_the_origin(configured: Any) -> None:
    configured(TRUSTED_A2A_AGENTS='["http://127.0.0.1:9100"]')

    assert get_settings().agent_card_base_url == "http://127.0.0.1:9100"


def test_with_nothing_configured_the_card_is_unavailable(
    client: TestClient, configured: Any
) -> None:
    configured(TRUSTED_A2A_AGENTS="[]")

    assert client.get("/api/v1/agents/analyst/card").status_code == 503


@pytest.mark.parametrize(
    "value",
    ["https://agents.example.com/some/path", "https://agents.example.com/?q=1", "ftp://x.example"],
)
def test_the_public_base_url_must_be_a_plain_origin(value: str) -> None:
    with pytest.raises(ValueError, match="A2A_PUBLIC_BASE_URL"):
        Settings(a2a_public_base_url=value)


# -- TrustedHostMiddleware --------------------------------------------------------------------


def test_by_default_any_host_is_accepted() -> None:
    client = TestClient(create_app(Settings()))

    assert client.get("/health", headers={"Host": "whatever.example"}).status_code == 200


def test_a_configured_host_list_refuses_other_hosts() -> None:
    client = TestClient(create_app(Settings(allowed_hosts=["api.example.test", "testserver"])))

    assert client.get("/health", headers={"Host": "api.example.test"}).status_code == 200
    assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400


def test_an_empty_host_list_is_refused() -> None:
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        Settings(allowed_hosts=[])
