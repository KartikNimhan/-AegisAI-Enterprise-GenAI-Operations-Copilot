"""The Copilot API module: one function, `run_multi_agent_workflow`, over
`POST /api/v1/multi-agent/run` (Milestone 8's
`app.api.schemas.multi_agent.MultiAgentRunResponse`, read directly from
the backend source to build these dataclasses — not reconstructed from
memory). This module performs no routing/orchestration of its own: it
only calls the one endpoint and parses its response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import request_json


@dataclass(frozen=True)
class AgentStatus:
    agent_name: str
    capability: str
    status: str
    error: str | None
    duration_ms: float
    retry_count: int


@dataclass(frozen=True)
class MultiAgentRunResult:
    workflow_id: str
    correlation_id: str
    status: str
    answer: str
    agents_used: list[AgentStatus] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


def run_multi_agent_workflow(message: str) -> MultiAgentRunResult:
    payload = request_json("POST", "/api/v1/multi-agent/run", json={"message": message})
    agents_used = [AgentStatus(**agent) for agent in payload.get("agents_used", [])]
    return MultiAgentRunResult(
        workflow_id=payload["workflow_id"],
        correlation_id=payload["correlation_id"],
        status=payload["status"],
        answer=payload["answer"],
        agents_used=agents_used,
        sources=payload.get("sources", []),
        token_usage=payload.get("token_usage", {}),
        duration_ms=payload.get("duration_ms", 0.0),
    )
