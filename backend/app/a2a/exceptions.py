"""Typed exceptions for the A2A client boundary.

Caught inside the `delegate_to_research_agent` tool (see
`app.agents.tools.research_delegation`) and converted into a `ToolResult`
before ever reaching the agent graph — the same "a remote failure never
crashes the agent" guarantee MCP and internal tools already give.
"""

from __future__ import annotations


class A2AError(Exception):
    """Base class for A2A-specific errors."""


class A2AUntrustedAgentError(A2AError):
    """The target base URL is not in `Settings.trusted_a2a_agents` — the
    client refuses to connect at all, before any network call."""


class A2AInvalidCardError(A2AError):
    """The fetched Agent Card is missing required fields, or its `name`
    does not match `Settings.research_agent_name` — a second, independent
    trust signal beyond the URL allowlist."""


class A2AConnectionError(A2AError):
    """The agent was unreachable (connection refused, DNS failure, etc.)."""


class A2ATimeoutError(A2AError):
    """A call exceeded `Settings.a2a_client_timeout_seconds`."""


class A2ATaskFailedError(A2AError):
    """The remote agent accepted the task but reported `TASK_STATE_FAILED`."""
