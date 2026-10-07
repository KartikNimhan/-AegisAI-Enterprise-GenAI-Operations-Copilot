"""Unit tests for `ResultAggregator`: single-success, analyst-synthesis,
partial-failure, and total-failure combinations — never fabricating a
result for an agent that didn't complete.
"""

from __future__ import annotations

from app.multi_agent.aggregation import ResultAggregator
from app.multi_agent.models import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    AgentResult,
)


def _result(agent_name: str, status: str, answer: str = "") -> AgentResult:
    return AgentResult(
        agent_name=agent_name, capability="x", task_id="t", status=status, answer=answer
    )


def test_single_success_surfaces_its_answer_directly() -> None:
    aggregator = ResultAggregator()
    answer, status = aggregator.combine(
        agent_results=[_result("research", STATUS_COMPLETED, "The policy says X.")]
    )
    assert answer == "The policy says X."
    assert status == STATUS_COMPLETED


def test_analyst_result_is_surfaced_as_the_final_synthesis() -> None:
    aggregator = ResultAggregator()
    answer, status = aggregator.combine(
        agent_results=[
            _result("document", STATUS_COMPLETED, "Doc metadata."),
            _result("analyst", STATUS_COMPLETED, "Synthesized comparison."),
        ]
    )
    assert answer == "Synthesized comparison."
    assert status == STATUS_COMPLETED


def test_partial_failure_still_surfaces_the_successful_answer() -> None:
    aggregator = ResultAggregator()
    answer, status = aggregator.combine(
        agent_results=[
            _result("research", STATUS_COMPLETED, "Found evidence."),
            _result("document", STATUS_TIMEOUT),
        ]
    )
    assert "Found evidence." in answer
    assert "document" in answer
    assert status == "partial"


def test_partial_failure_never_claims_the_failed_agent_succeeded() -> None:
    aggregator = ResultAggregator()
    answer, _status = aggregator.combine(
        agent_results=[
            _result("research", STATUS_COMPLETED, "Found evidence."),
            _result("document", STATUS_FAILED),
        ]
    )
    assert "did not complete" in answer


def test_total_failure_returns_a_failed_status_with_no_fabricated_answer() -> None:
    aggregator = ResultAggregator()
    answer, status = aggregator.combine(
        agent_results=[_result("research", STATUS_FAILED), _result("document", STATUS_TIMEOUT)]
    )
    assert status == STATUS_FAILED
    assert "research" in answer
    assert "document" in answer


def test_empty_agent_results_is_completed_with_an_empty_answer() -> None:
    aggregator = ResultAggregator()
    answer, status = aggregator.combine(agent_results=[])
    assert answer == ""
    assert status == STATUS_COMPLETED
