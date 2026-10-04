"""Agent workflow state and orchestration result types.

`AgentState` is LangGraph's state schema — workflow state only (the
in-flight message list, step/tool-call counters, run status). It is
deliberately not, and must never become, a duplicate of the persisted
`Conversation`/`Message` domain models: `AgentService` reads prior
history from `MessageRepository` once at the start of a run and persists
only the final user/assistant turn at the end, the same boundary
`ChatService`/`RAGService` already use. Everything in between — tool
calls, tool results, intermediate LLM turns — lives only in `AgentState`
for the duration of the run and is never written to the conversation
history (see ADR 008, "Conversation integration").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# Run statuses. "completed" is the only "the agent decided it was done"
# outcome; the other two are controlled-stop safety outcomes reached from
# inside the graph (see ADR 008, "Maximum steps"). A timeout is a distinct,
# separate case — it never produces one of these statuses at all, since the
# run didn't finish; it propagates as `AgentTimeoutError` to an HTTP 504
# instead (see `app.agents.exceptions`).
STATUS_COMPLETED = "completed"
STATUS_MAX_STEPS_EXCEEDED = "max_steps_exceeded"
STATUS_MAX_TOOL_CALLS_EXCEEDED = "max_tool_calls_exceeded"


class AgentState(TypedDict):
    """`messages` uses LangGraph's `add_messages` reducer (append, with
    id-based replacement) — the standard, current (v1.x) way to accumulate
    a message list across graph steps without each node having to manually
    concatenate lists."""

    messages: Annotated[list[BaseMessage], add_messages]
    step_count: int
    tool_call_count: int
    tool_calls_by_name: dict[str, int]
    status: str


@dataclass(frozen=True)
class ToolUsageSummary:
    """Aggregated per-tool counts for the API response."""

    name: str
    call_count: int
    success_count: int
    failure_count: int


@dataclass(frozen=True)
class AgentSource:
    """One knowledge-base result the agent consulted via
    `search_knowledge_base`, surfaced for transparency — not a `[S1]`-style
    inline citation the way `app.rag.schemas.RAGSource` is, since the agent
    prompt doesn't mandate that citation format (see ADR 008)."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    similarity: float


@dataclass(frozen=True)
class AgentRunResult:
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    answer: str
    status: str
    steps: int
    tool_calls: list[ToolUsageSummary]
    sources: list[AgentSource] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass(frozen=True)
class AgentStreamEvent:
    """One SSE-safe event for the streaming endpoint.

    `event` is one of `"tool_started"`, `"tool_completed"`, `"answer_delta"`,
    or `"completed"` — never anything carrying an intermediate `AIMessage`'s
    free-text content (which could contain the model's reasoning about
    which tool to call and why — see ADR 008, "Streaming"). `data` is a
    small, JSON-safe dict specific to the event type (e.g. `{"tool_name":
    ...}` for `tool_started`, `{"delta": ...}` for `answer_delta`).
    """

    event: str
    data: dict[str, object]
