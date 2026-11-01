"""Cost protection for model calls (AIGSEC-009): a per-call input budget in the gateway, a total
evidence cap on the Analyst Agent, evidence trimming in the orchestrator, and bounded retries.

No real model is called: the provider is scripted, and every "oversized" case checks that the
provider was never reached.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.a2a.analyst_agent import AnalystAgentService
from app.a2a.schemas import AnalystAgentResult
from app.api.v1.analyst_agent import get_analyst_agent_service
from app.config import Settings
from app.core.exceptions import register_exception_handlers
from app.llm.exceptions import LLMInputTooLargeError
from app.llm.gateway import LLMGateway, input_size
from app.llm.schemas import (
    ChatMessage,
    ChatRole,
    CompletionResponse,
    ModelRole,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from app.main import app
from app.multi_agent.adapters import TRUNCATION_MARK, fit_evidence

from .doubles import ScriptedProvider

BUDGET = 1_000


def _gateway(provider: ScriptedProvider, budget: int = BUDGET) -> LLMGateway:
    return LLMGateway(Settings(llm_max_input_chars=budget), provider=provider)


def _ok() -> CompletionResponse:
    return CompletionResponse(content="ok", model="m", provider="fake", usage=TokenUsage())


def _messages(chars: int) -> list[ChatMessage]:
    return [
        ChatMessage(role=ChatRole.SYSTEM, content="s" * 10),
        ChatMessage(role=ChatRole.USER, content="u" * (chars - 10)),
    ]


# -- the gateway's per-call budget -------------------------------------------------------------


async def test_a_request_within_the_budget_reaches_the_provider() -> None:
    provider = ScriptedProvider([_ok()])

    result = await _gateway(provider).chat_completion(
        model_role=ModelRole.FAST, messages=_messages(BUDGET)
    )

    assert result.content == "ok"
    assert len(provider.calls) == 1


async def test_an_oversized_request_fails_before_the_provider_is_called() -> None:
    provider = ScriptedProvider([_ok(), _ok(), _ok()])

    with pytest.raises(LLMInputTooLargeError):
        await _gateway(provider).chat_completion(
            model_role=ModelRole.FAST, messages=_messages(BUDGET + 1)
        )

    assert provider.calls == []  # nothing sent, nothing billed, nothing retried


async def test_an_oversized_stream_fails_before_the_provider_is_called() -> None:
    provider = ScriptedProvider([[StreamChunk(delta="never")]])

    with pytest.raises(LLMInputTooLargeError):
        async for _ in _gateway(provider).stream_chat_completion(
            model_role=ModelRole.FAST, messages=_messages(BUDGET + 1)
        ):
            pass

    assert provider.calls == []


def test_tool_call_arguments_count_towards_the_budget() -> None:
    messages = [
        ChatMessage(
            role=ChatRole.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="1", name="search", arguments='{"q": "' + "x" * 50 + '"}')],
        ),
        ChatMessage(role=ChatRole.TOOL, content="r" * 20, tool_call_id="1"),
    ]

    assert input_size(messages) == len("search") + len('{"q": "' + "x" * 50 + '"}') + 20


async def test_tool_results_accumulating_in_an_agent_run_are_bounded_too() -> None:
    # An agent's prompt grows with every tool result; the same budget applies to each call.
    provider = ScriptedProvider([_ok()])
    messages = [
        ChatMessage(role=ChatRole.USER, content="question"),
        ChatMessage(role=ChatRole.TOOL, content="z" * BUDGET, tool_call_id="1"),
    ]

    with pytest.raises(LLMInputTooLargeError):
        await _gateway(provider).chat_completion(model_role=ModelRole.PRIMARY, messages=messages)
    assert provider.calls == []


def test_the_error_maps_to_413_with_a_fixed_message() -> None:
    mini = FastAPI()
    register_exception_handlers(mini)

    @mini.get("/x")
    async def x() -> None:
        raise LLMInputTooLargeError("internal detail 123456", provider="fake")

    response = TestClient(mini).get("/x")

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "llm_input_too_large"
    assert "123456" not in response.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"llm_max_retries": 6},
        {"llm_max_retries": -1},
        {"llm_max_input_chars": 999},
        {"analyst_max_evidence_total_chars": 999},
    ],
)
def test_cost_bounds_are_validated(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Settings(**overrides)  # type: ignore[arg-type]


# -- the analyst's total evidence ---------------------------------------------------------------


class _CountingAnalyst(AnalystAgentService):
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, **_kwargs: Any) -> AnalystAgentResult:
        self.calls += 1
        return AnalystAgentResult(status="completed", answer="fine")


@pytest.fixture
def analyst() -> Iterator[_CountingAnalyst]:
    service = _CountingAnalyst()
    app.dependency_overrides[get_analyst_agent_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_analyst_agent_service, None)


def _submit(client: TestClient, evidence: list[str], monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(
        "app.api.v1.analyst_agent.get_settings",
        lambda: Settings(analyst_max_evidence_total_chars=1_000),
    )
    return client.post(
        "/api/v1/agents/analyst/tasks", json={"question": "Summarise", "evidence": evidence}
    )


def test_evidence_within_the_total_is_analysed(
    client: TestClient, analyst: _CountingAnalyst, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _submit(client, ["a" * 500, "b" * 500], monkeypatch)

    assert response.status_code == 200
    assert analyst.calls == 1


def test_evidence_over_the_total_is_refused_before_any_model_call(
    client: TestClient, analyst: _CountingAnalyst, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each item is within its own limit; together they are not.
    response = _submit(client, ["a" * 600, "b" * 600], monkeypatch)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "evidence_too_large"
    assert analyst.calls == 0


# -- the orchestrator keeps within it -------------------------------------------------------


def test_evidence_that_fits_is_passed_unchanged() -> None:
    assert fit_evidence(["one", "two"], 100) == ["one", "two"]


def test_the_item_that_crosses_the_limit_is_cut_and_later_ones_dropped() -> None:
    fitted = fit_evidence(["a" * 60, "b" * 60, "c" * 60], 100)

    assert fitted[0] == "a" * 60
    assert fitted[1].endswith(TRUNCATION_MARK)
    assert len("".join(fitted)) <= 100
    assert len(fitted) == 2


def test_trimmed_evidence_always_fits_the_analysts_cap() -> None:
    cap = Settings().analyst_max_evidence_total_chars
    fitted = fit_evidence(["x" * 40_000, "y" * 40_000, "z" * 40_000], cap)

    assert sum(len(item) for item in fitted) <= cap
