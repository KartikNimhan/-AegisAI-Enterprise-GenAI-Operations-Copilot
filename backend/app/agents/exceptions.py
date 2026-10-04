"""Typed exceptions for agent orchestration.

Deliberately minimal, mirroring `app.rag.exceptions`: most agent failure
modes are controlled, in-band results, not exceptions — hitting
`AGENT_MAX_STEPS`/`AGENT_MAX_TOOL_CALLS` produces a normal `AgentRunResult`
with a `max_*_exceeded` status (like RAG's `has_context: false`, not an
HTTP error), and tool failures become structured `ToolResult`s the model
sees as data. Query-embedding and LLM-generation failures already have
typed exceptions elsewhere (`EmbeddingProviderError`/`LLMError`) and are
reused, not duplicated, by `AgentService` — see `app.rag.exceptions` for
the same reasoning applied to RAG.

`AgentTimeoutError` is the one genuinely new exception: a run exceeding
`AGENT_TIMEOUT_SECONDS` is a wall-clock backstop around the whole graph
invocation (via `asyncio.wait_for`), not something any inner component can
express as an in-band state.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for agent-specific errors not already covered by an
    existing typed exception elsewhere in the codebase."""


class AgentTimeoutError(AgentError):
    """Raised when a run exceeds `Settings.agent_timeout_seconds`. Unlike
    `max_steps`/`max_tool_calls` (which are controlled, in-band
    `AgentRunResult` outcomes — the agent safely stopped itself), a timeout
    means the run did not complete within its wall-clock budget at all, so
    this propagates to a registered handler (`app.core.exceptions`) mapped
    to HTTP 504 — the same distinction, and the same status code,
    `LLMTimeoutError` already uses."""
