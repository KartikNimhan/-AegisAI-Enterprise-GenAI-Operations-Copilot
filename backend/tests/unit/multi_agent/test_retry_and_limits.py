"""Unit tests for the orchestrator's retry policy, loop/delegation
limits, and the overall workflow timeout backstop — exercised directly
against `MultiAgentOrchestrator` with the adapter layer patched, so each
scenario is deterministic and doesn't depend on the full A2A/HTTP
round-trip (already covered by test_orchestrator.py).
"""

from __future__ import annotations

import asyncio

import pytest

import app.multi_agent.orchestrator as orchestrator_module
from app.a2a.client import A2AClient
from app.config import Settings
from app.llm.gateway import LLMGateway
from app.llm.schemas import CompletionResponse, TokenUsage
from app.multi_agent.models import STATUS_COMPLETED, STATUS_FAILED, STATUS_TIMEOUT, AgentResult
from app.multi_agent.orchestrator import MultiAgentOrchestrator


class _FakeGateway(LLMGateway):
    def __init__(self) -> None:
        pass

    async def chat_completion(self, **kwargs: object) -> CompletionResponse:
        return CompletionResponse(
            content="direct answer", model="m", provider="test", usage=TokenUsage()
        )


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "multi_agent_timeout_seconds": 5.0,
        "multi_agent_agent_timeout_seconds": 5.0,
        "multi_agent_max_retries": 1,
        "max_agent_depth": 2,
        "max_agent_delegations": 5,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _make_orchestrator(settings: Settings) -> MultiAgentOrchestrator:
    return MultiAgentOrchestrator(
        settings=settings, gateway=_FakeGateway(), a2a_client=A2AClient(settings=settings)
    )


def _result(status: str, *, retryable: bool = False) -> AgentResult:
    return AgentResult(
        agent_name="research",
        capability="research",
        task_id="t",
        status=status,
        answer="ok" if status == STATUS_COMPLETED else "",
        metadata={"retryable": retryable},
    )


@pytest.fixture
def patch_route_to_research(monkeypatch: pytest.MonkeyPatch):
    from app.multi_agent.router import RoutingDecision

    monkeypatch.setattr(
        orchestrator_module, "route", lambda message: RoutingDecision(capabilities=("research",))
    )


async def test_retry_succeeds_after_one_transient_failure(
    monkeypatch: pytest.MonkeyPatch, patch_route_to_research
) -> None:
    calls = {"count": 0}

    async def _flaky(*, client, settings, context):
        calls["count"] += 1
        if calls["count"] == 1:
            return _result(STATUS_FAILED, retryable=True)
        return _result(STATUS_COMPLETED)

    monkeypatch.setitem(orchestrator_module._ADAPTER_BY_AGENT, "research", _flaky)
    orchestrator = _make_orchestrator(_settings(multi_agent_max_retries=1))

    result = await orchestrator.run(question="research something")

    assert calls["count"] == 2
    assert result.agent_results[0].status == STATUS_COMPLETED
    assert result.agent_results[0].retry_count == 1


async def test_retry_exhaustion_returns_a_failed_result(
    monkeypatch: pytest.MonkeyPatch, patch_route_to_research
) -> None:
    calls = {"count": 0}

    async def _always_fails(*, client, settings, context):
        calls["count"] += 1
        return _result(STATUS_FAILED, retryable=True)

    monkeypatch.setitem(orchestrator_module._ADAPTER_BY_AGENT, "research", _always_fails)
    orchestrator = _make_orchestrator(_settings(multi_agent_max_retries=2))

    result = await orchestrator.run(question="research something")

    assert calls["count"] == 3  # 1 initial attempt + 2 retries
    assert result.agent_results[0].status == STATUS_FAILED
    assert result.agent_results[0].retry_count == 2
    assert result.status == STATUS_FAILED


async def test_non_retryable_failure_is_never_retried(
    monkeypatch: pytest.MonkeyPatch, patch_route_to_research
) -> None:
    calls = {"count": 0}

    async def _permanent_failure(*, client, settings, context):
        calls["count"] += 1
        return _result(STATUS_FAILED, retryable=False)

    monkeypatch.setitem(orchestrator_module._ADAPTER_BY_AGENT, "research", _permanent_failure)
    orchestrator = _make_orchestrator(_settings(multi_agent_max_retries=3))

    result = await orchestrator.run(question="research something")

    assert calls["count"] == 1
    assert result.agent_results[0].retry_count == 0


async def test_timeout_status_is_also_retryable(
    monkeypatch: pytest.MonkeyPatch, patch_route_to_research
) -> None:
    calls = {"count": 0}

    async def _times_out_once(*, client, settings, context):
        calls["count"] += 1
        if calls["count"] == 1:
            return _result(STATUS_TIMEOUT, retryable=True)
        return _result(STATUS_COMPLETED)

    monkeypatch.setitem(orchestrator_module._ADAPTER_BY_AGENT, "research", _times_out_once)
    orchestrator = _make_orchestrator(_settings(multi_agent_max_retries=1))

    result = await orchestrator.run(question="research something")

    assert calls["count"] == 2
    assert result.agent_results[0].status == STATUS_COMPLETED


# -- Loop/delegation limits -----------------------------------------------------------


async def test_delegation_limit_exceeded_fails_the_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.multi_agent.router import RoutingDecision

    monkeypatch.setattr(
        orchestrator_module,
        "route",
        lambda message: RoutingDecision(capabilities=("research", "document_analysis")),
    )
    orchestrator = _make_orchestrator(_settings(max_agent_delegations=1))

    result = await orchestrator.run(question="compare things")

    assert result.status == STATUS_FAILED
    assert result.agent_results == []


async def test_workflow_depth_exceeded_fails_the_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.multi_agent.router import RoutingDecision

    monkeypatch.setattr(
        orchestrator_module,
        "route",
        lambda message: RoutingDecision(capabilities=("research", "synthesis")),
    )
    orchestrator = _make_orchestrator(_settings(max_agent_depth=1))

    result = await orchestrator.run(question="research and synthesize")

    assert result.status == STATUS_FAILED
    assert result.agent_results == []


# -- Overall workflow timeout (coarse backstop) ----------------------------------------


async def test_overall_workflow_timeout_returns_a_timeout_status(
    monkeypatch: pytest.MonkeyPatch, patch_route_to_research
) -> None:
    async def _hangs(*, client, settings, context):
        await asyncio.sleep(5)
        return _result(STATUS_COMPLETED)  # pragma: no cover - never reached

    monkeypatch.setitem(orchestrator_module._ADAPTER_BY_AGENT, "research", _hangs)
    orchestrator = _make_orchestrator(
        _settings(multi_agent_timeout_seconds=0.05, multi_agent_agent_timeout_seconds=5.0)
    )

    result = await orchestrator.run(question="research something")

    assert result.status == STATUS_TIMEOUT
    assert result.agent_results == []
