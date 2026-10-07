"""Typed exceptions for the multi-agent orchestration boundary.

Distinguished from `app.a2a.exceptions.A2AError` (a single agent call's
own transport/protocol failures, still raised and handled per-call): these
are workflow-level policy violations — a request trying to exceed the
orchestrator's own loop/authorization guarantees, never a transient
remote failure. None of these are ever retried.
"""

from __future__ import annotations


class MultiAgentError(Exception):
    """Base class for multi-agent orchestration errors."""


class WorkflowDepthExceededError(MultiAgentError):
    """A delegation would exceed `Settings.max_agent_depth`."""


class DelegationLimitExceededError(MultiAgentError):
    """A workflow would exceed `Settings.max_agent_delegations` total
    agent calls."""


class UnauthorizedAgentError(MultiAgentError):
    """The requested agent is not in the static capability registry."""


class UnauthorizedCapabilityError(MultiAgentError):
    """The requested capability is not one the target agent is
    authorized for (checked against both the static policy and the
    agent's own discovered Agent Card skills)."""


class InvalidWorkflowTransitionError(MultiAgentError):
    """The requested agent-to-agent transition is not in
    `app.multi_agent.policies.ALLOWED_TRANSITIONS`."""
