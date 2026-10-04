"""Unit tests for the agent API endpoints.

The `AgentService` dependency is overridden with a fake — no real
LangGraph execution, database, model, or Groq call is involved.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.exceptions import AgentTimeoutError
from app.agents.schemas import (
    STATUS_COMPLETED,
    AgentRunResult,
    AgentSource,
    AgentStreamEvent,
    ToolUsageSummary,
)
from app.agents.service import AgentService, get_agent_service
from app.core.exceptions import NotFoundError
from app.llm.exceptions import LLMTimeoutError
from app.main import app

_CONVERSATION_ID = uuid.uuid4()


def make_result(**overrides: Any) -> AgentRunResult:
    defaults: dict[str, Any] = {
        "run_id": uuid.uuid4(),
        "conversation_id": _CONVERSATION_ID,
        "answer": "The result is 45.",
        "status": STATUS_COMPLETED,
        "steps": 2,
        "tool_calls": [
            ToolUsageSummary(name="calculator", call_count=1, success_count=1, failure_count=0)
        ],
        "sources": [],
        "duration_ms": 123.4,
    }
    defaults.update(overrides)
    return AgentRunResult(**defaults)


class FakeAgentService(AgentService):
    def __init__(
        self,
        *,
        run_result: AgentRunResult | None = None,
        run_error: Exception | None = None,
        stream_events: list[tuple[str, dict[str, Any]]] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self._run_result = run_result
        self._run_error = run_error
        self._stream_events = stream_events or []
        self._stream_error = stream_error
        self.calls: list[dict[str, Any]] = []

    async def run(
        self, *, conversation_id: uuid.UUID | None, message: str, model_role: Any = None
    ) -> AgentRunResult:
        self.calls.append({"conversation_id": conversation_id, "message": message})
        if self._run_error is not None:
            raise self._run_error
        assert self._run_result is not None
        return self._run_result

    async def run_stream(
        self, *, conversation_id: uuid.UUID | None, message: str, model_role: Any = None
    ) -> AsyncIterator[tuple[uuid.UUID, Any]]:
        self.calls.append({"conversation_id": conversation_id, "message": message})
        if self._stream_error is not None:
            raise self._stream_error
        resolved_id = conversation_id or _CONVERSATION_ID
        for event_name, data in self._stream_events:
            yield resolved_id, AgentStreamEvent(event=event_name, data=data)


@pytest.fixture
def override_agent_service() -> Iterator[Any]:
    def _override(fake_service: AgentService) -> None:
        app.dependency_overrides[get_agent_service] = lambda: fake_service

    yield _override
    app.dependency_overrides.clear()


def test_run_agent_returns_final_answer_and_tool_usage(
    client: TestClient, override_agent_service: Any
) -> None:
    override_agent_service(FakeAgentService(run_result=make_result()))

    response = client.post("/api/v1/agents/run", json={"message": "What is 250 * 0.18?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The result is 45."
    assert body["status"] == "completed"
    assert body["steps"] == 2
    assert body["tool_usage"][0]["name"] == "calculator"
    assert body["tool_usage"][0]["call_count"] == 1
    assert "run_id" in body
    assert "conversation_id" in body


def test_run_agent_never_exposes_internal_graph_state(
    client: TestClient, override_agent_service: Any
) -> None:
    override_agent_service(FakeAgentService(run_result=make_result()))

    response = client.post("/api/v1/agents/run", json={"message": "question"})

    body = response.json()
    assert "messages" not in body
    assert "tool_calls_by_name" not in body
    assert "step_count" not in body


def test_run_agent_includes_sources_when_knowledge_base_was_used(
    client: TestClient, override_agent_service: Any
) -> None:
    result = make_result(
        sources=[
            AgentSource(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                filename="Travel Policy.pdf",
                page_number=4,
                similarity=0.82,
            )
        ]
    )
    override_agent_service(FakeAgentService(run_result=result))

    response = client.post("/api/v1/agents/run", json={"message": "question"})

    body = response.json()
    assert len(body["sources"]) == 1
    assert body["sources"][0]["filename"] == "Travel Policy.pdf"
    assert body["sources"][0]["page"] == 4


def test_run_agent_rejects_empty_message(client: TestClient, override_agent_service: Any) -> None:
    override_agent_service(FakeAgentService(run_result=make_result()))

    response = client.post("/api/v1/agents/run", json={"message": ""})

    assert response.status_code == 422


def test_run_agent_returns_404_for_unknown_conversation(
    client: TestClient, override_agent_service: Any
) -> None:
    override_agent_service(FakeAgentService(run_error=NotFoundError("Conversation not found")))

    response = client.post(
        "/api/v1/agents/run", json={"message": "q", "conversation_id": str(uuid.uuid4())}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_run_agent_returns_504_on_timeout(client: TestClient, override_agent_service: Any) -> None:
    override_agent_service(
        FakeAgentService(run_error=AgentTimeoutError("Agent run exceeded 60.0s"))
    )

    response = client.post("/api/v1/agents/run", json={"message": "q"})

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "agent_timeout"


def test_run_agent_maps_llm_errors_to_http_status(
    client: TestClient, override_agent_service: Any
) -> None:
    override_agent_service(
        FakeAgentService(run_error=LLMTimeoutError("timed out", provider="groq"))
    )

    response = client.post("/api/v1/agents/run", json={"message": "q"})

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "llm_timeout"


def test_run_agent_stream_emits_safe_events(
    client: TestClient, override_agent_service: Any
) -> None:
    fake = FakeAgentService(
        stream_events=[
            ("tool_started", {"tool_name": "calculator"}),
            ("tool_completed", {"tool_name": "calculator", "success": True}),
            ("answer_delta", {"delta": "The result is 45."}),
            ("completed", {"status": "completed"}),
        ]
    )
    override_agent_service(fake)

    with client.stream("POST", "/api/v1/agents/run/stream", json={"message": "q"}) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "tool_started" in body
    assert "tool_completed" in body
    assert "answer_delta" in body
    assert "The result is 45." in body
    assert "completed" in body


def test_run_agent_stream_never_exposes_reasoning_field(
    client: TestClient, override_agent_service: Any
) -> None:
    fake = FakeAgentService(
        stream_events=[
            ("answer_delta", {"delta": "answer"}),
            ("completed", {"status": "completed"}),
        ]
    )
    override_agent_service(fake)

    with client.stream("POST", "/api/v1/agents/run/stream", json={"message": "q"}) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert "reasoning" not in body
    assert "chain_of_thought" not in body


def test_run_agent_stream_emits_error_event_on_failure(
    client: TestClient, override_agent_service: Any
) -> None:
    override_agent_service(
        FakeAgentService(stream_error=LLMTimeoutError("timed out", provider="groq"))
    )

    with client.stream("POST", "/api/v1/agents/run/stream", json={"message": "q"}) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "LLMTimeoutError" in body
