"""Unit tests for the deterministic routing policy — the brief's 7
routing scenarios plus the edge cases that motivated specific fixes
(UUID/arithmetic collision, small talk, comparison without a document id).
"""

from __future__ import annotations

import uuid

from app.multi_agent.capabilities import (
    CAPABILITY_CALCULATION,
    CAPABILITY_DOCUMENT_ANALYSIS,
    CAPABILITY_RESEARCH,
    CAPABILITY_SYNTHESIS,
)
from app.multi_agent.router import route


def test_direct_answer_for_small_talk() -> None:
    decision = route("Hello")
    assert decision.capabilities == ()


def test_calculation_only_for_a_percentage_question() -> None:
    decision = route("What is 15% of 500?")
    assert decision.capabilities == (CAPABILITY_CALCULATION,)
    assert decision.expressions == ["15/100*500"]


def test_calculation_only_for_a_plain_arithmetic_question() -> None:
    decision = route("Please calculate 12 + 30 for me")
    assert decision.capabilities == (CAPABILITY_CALCULATION,)


def test_research_only_for_a_policy_question() -> None:
    decision = route("What does our travel policy say about hotel reimbursement?")
    assert decision.capabilities == (CAPABILITY_RESEARCH,)


def test_document_only_for_a_single_document_id() -> None:
    document_id = uuid.uuid4()
    decision = route(f"Tell me the metadata and status of document {document_id}.")
    assert decision.capabilities == (CAPABILITY_DOCUMENT_ANALYSIS,)
    assert decision.document_ids == [document_id]


def test_research_and_document_and_synthesis_for_a_comparison() -> None:
    document_id = uuid.uuid4()
    decision = route(f"Compare the travel reimbursement policy with document {document_id}.")
    assert set(decision.capabilities) == {
        CAPABILITY_RESEARCH,
        CAPABILITY_DOCUMENT_ANALYSIS,
        CAPABILITY_SYNTHESIS,
    }


def test_research_and_calculation_and_synthesis_for_research_plus_calculate() -> None:
    decision = route(
        "Research the travel policy and calculate the reimbursement for "
        "three nights at $180 per night."
    )
    assert CAPABILITY_RESEARCH in decision.capabilities
    assert CAPABILITY_CALCULATION in decision.capabilities
    assert CAPABILITY_SYNTHESIS in decision.capabilities


def test_document_id_inside_message_never_triggers_calculation() -> None:
    """A regression test for a real bug found during manual verification:
    a UUID's hyphen-joined hex groups look exactly like a subtraction
    expression to a naive arithmetic regex."""
    document_id = uuid.uuid4()
    decision = route(f"What is the status of {document_id}?")
    assert CAPABILITY_CALCULATION not in decision.capabilities
    assert decision.capabilities == (CAPABILITY_DOCUMENT_ANALYSIS,)


def test_comparing_two_document_ids_adds_synthesis() -> None:
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    decision = route(f"Compare document {first_id} with document {second_id}.")
    assert CAPABILITY_SYNTHESIS in decision.capabilities


def test_routing_never_produces_an_unknown_capability() -> None:
    known = {
        CAPABILITY_RESEARCH,
        CAPABILITY_DOCUMENT_ANALYSIS,
        CAPABILITY_CALCULATION,
        CAPABILITY_SYNTHESIS,
    }
    for message in (
        "hello",
        "What is 2 + 2?",
        f"document {uuid.uuid4()}",
        "Compare our policy with the law",
        "asdkjalksjd random gibberish !!! 12831 09",
    ):
        decision = route(message)
        assert set(decision.capabilities) <= known
