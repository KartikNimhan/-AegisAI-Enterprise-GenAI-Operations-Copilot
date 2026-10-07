"""Workflow transition policy: which agent-to-agent transitions are
allowed, so the orchestrator can never build an uncontrolled agent
network (see docs/architecture/decisions/010-multi-agent-architecture.md,
"Workflow policy").

Transient vs permanent failure classification lives here too: it decides
what `orchestrator.py`'s retry loop is allowed to retry.
"""

from __future__ import annotations

from app.a2a.exceptions import A2AConnectionError, A2ATimeoutError
from app.multi_agent.capabilities import AGENT_ANALYST, AGENT_DOCUMENT, AGENT_RESEARCH

ORCHESTRATOR = "orchestrator"

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ORCHESTRATOR: frozenset({AGENT_RESEARCH, AGENT_DOCUMENT, AGENT_ANALYST}),
    AGENT_RESEARCH: frozenset({AGENT_ANALYST}),
    AGENT_DOCUMENT: frozenset({AGENT_ANALYST}),
    AGENT_ANALYST: frozenset(),
}

# Only these exception types are ever retried — a transient transport
# failure, never a validation/authorization/task-content failure (see
# A2AUntrustedAgentError/A2AInvalidCardError/A2ATaskFailedError, all of
# which are permanent and never retried).
RETRYABLE_A2A_EXCEPTIONS: tuple[type[Exception], ...] = (A2AConnectionError, A2ATimeoutError)


def is_transition_allowed(*, source: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(source, frozenset())
