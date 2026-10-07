"""Unit tests for the static capability registry and workflow transition
policy — the orchestrator's "hard boundary" guarantees.
"""

from __future__ import annotations

from app.a2a.exceptions import A2AConnectionError, A2AInvalidCardError, A2ATimeoutError
from app.multi_agent.capabilities import (
    AGENT_ANALYST,
    AGENT_DOCUMENT,
    AGENT_RESEARCH,
    CAPABILITY_CALCULATION,
    CAPABILITY_DOCUMENT_ANALYSIS,
    CAPABILITY_RESEARCH,
    CAPABILITY_SYNTHESIS,
    agent_for_capability,
)
from app.multi_agent.policies import (
    ORCHESTRATOR,
    RETRYABLE_A2A_EXCEPTIONS,
    is_transition_allowed,
)


def test_each_capability_maps_to_exactly_one_agent() -> None:
    assert agent_for_capability(CAPABILITY_RESEARCH) == AGENT_RESEARCH
    assert agent_for_capability(CAPABILITY_DOCUMENT_ANALYSIS) == AGENT_DOCUMENT
    assert agent_for_capability(CAPABILITY_CALCULATION) == AGENT_ANALYST
    assert agent_for_capability(CAPABILITY_SYNTHESIS) == AGENT_ANALYST


def test_unknown_capability_maps_to_no_agent() -> None:
    assert agent_for_capability("delete_everything") is None


def test_orchestrator_may_call_all_three_agents() -> None:
    assert is_transition_allowed(source=ORCHESTRATOR, target=AGENT_RESEARCH)
    assert is_transition_allowed(source=ORCHESTRATOR, target=AGENT_DOCUMENT)
    assert is_transition_allowed(source=ORCHESTRATOR, target=AGENT_ANALYST)


def test_analyst_may_not_delegate_further() -> None:
    assert not is_transition_allowed(source=AGENT_ANALYST, target=AGENT_RESEARCH)
    assert not is_transition_allowed(source=AGENT_ANALYST, target=AGENT_DOCUMENT)
    assert not is_transition_allowed(source=AGENT_ANALYST, target=AGENT_ANALYST)


def test_research_and_document_may_only_reach_analyst() -> None:
    assert is_transition_allowed(source=AGENT_RESEARCH, target=AGENT_ANALYST)
    assert not is_transition_allowed(source=AGENT_RESEARCH, target=AGENT_DOCUMENT)
    assert is_transition_allowed(source=AGENT_DOCUMENT, target=AGENT_ANALYST)
    assert not is_transition_allowed(source=AGENT_DOCUMENT, target=AGENT_RESEARCH)


def test_only_transient_a2a_errors_are_retryable() -> None:
    assert A2AConnectionError in RETRYABLE_A2A_EXCEPTIONS
    assert A2ATimeoutError in RETRYABLE_A2A_EXCEPTIONS
    assert A2AInvalidCardError not in RETRYABLE_A2A_EXCEPTIONS
