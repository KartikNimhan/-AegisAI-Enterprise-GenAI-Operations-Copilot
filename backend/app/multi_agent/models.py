"""Typed context/result/workflow models for multi-agent orchestration.

`AgentContext` is the *only* thing a specialized agent call receives from
the orchestrator — never the full conversation history, another agent's
internal reasoning, or unrelated database content (see
docs/architecture/decisions/010-multi-agent-architecture.md, "Context
isolation"). `AgentResult` is the one structured shape every specialized
agent's response is normalized into before the orchestrator reasons about
it further, regardless of which A2A agent produced it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_UNAUTHORIZED = "unauthorized"
STATUS_PARTIAL = "partial"


@dataclass(frozen=True)
class AgentContext:
    """The minimum structured input one specialized agent call needs —
    deliberately not a dict grab-bag of "everything available"."""

    task_id: str
    correlation_id: str
    workflow_id: str
    user_question: str
    document_ids: list[uuid.UUID] = field(default_factory=list)
    expressions: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    depth: int = 1


@dataclass(frozen=True)
class AgentResult:
    """The one structured shape every specialized agent's response is
    normalized into, whether it came from Research, Document, or
    Analyst — `agent_name`/`capability` distinguish the source without
    the orchestrator needing a different result type per agent."""

    agent_name: str
    capability: str
    task_id: str
    status: str
    answer: str
    sources: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    retry_count: int = 0


@dataclass(frozen=True)
class WorkflowResult:
    workflow_id: str
    correlation_id: str
    status: str
    answer: str
    agent_results: list[AgentResult] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    duration_ms: float = 0.0
