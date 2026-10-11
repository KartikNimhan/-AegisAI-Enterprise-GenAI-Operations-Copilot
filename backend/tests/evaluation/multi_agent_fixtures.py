"""A small, deterministic multi-agent evaluation fixture (M11 Phase 2).

Not a test module itself (no `test_*` functions) — mirrors
`agent_fixtures.py`'s shape for the single-agent path, but for
`MultiAgentOrchestrator`. Each `MultiAgentScenario` drives the real
`POST /api/v1/multi-agent/run` endpoint (routing, parallel/sequential
execution, aggregation, retries — the real orchestrator code, not a
reimplementation of it) with a scripted LLM gateway and a fake retrieval
strategy, exactly like `tests/unit/multi_agent/test_orchestrator.py`
already does via its `orchestrator_env`/`async_client` fixtures. This is
deliberately NOT a new mocking seam: it reuses that existing,
already-proven harness so this evaluation fixture can never drift from
what the orchestrator unit tests already verify is correct.

Why this file exists alongside test_orchestrator.py's already-thorough
coverage (routing, parallel/sequential, partial failure, timeout,
security, observability): that suite is a correctness regression test
for the orchestrator's implementation. This fixture packages a *named,
printable* subset of the same kind of scenarios into the evaluation
suite's own scenario-table/pass-fail-summary form (see
test_multi_agent_evaluation.py), the same shape agent_fixtures.py/
test_agent_evaluation.py already gives the single-agent path — so the
M11 evaluation report has an entry for "does multi-agent orchestration
behave as designed" alongside its single-agent counterpart. It asserts
observable outcomes only (expected agent path, context/citation
metadata retention across a tier1 -> Analyst handoff, graceful error
handling) — never a claim about a *live* model choosing the right route
unprompted, since routing itself here is still the deterministic
keyword-based `app.multi_agent.router.route`, not an LLM decision.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.llm.schemas import CompletionResponse, TokenUsage

from ..unit.rag.doubles import make_result


@dataclass(frozen=True)
class MultiAgentScenario:
    name: str
    message: str
    expected_status: str
    expected_agents_used: set[str] = field(default_factory=set)
    expect_answer_contains: str | None = None
    expect_sources_filename: str | None = None
    retrieval_results: list | None = None
    gateway_completion: CompletionResponse | None = None
    seed_document: bool = False
    document_id: uuid.UUID | None = None


# A single document id shared between the "document" scenarios and the
# fake document repository they seed — see
# test_multi_agent_evaluation.py's use of `fake_documents`.
SAMPLE_DOCUMENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

SCENARIOS: list[MultiAgentScenario] = [
    MultiAgentScenario(
        name="direct_answer_no_agent_needed",
        message="hello",
        expected_status="completed",
        expected_agents_used=set(),
        expect_answer_contains="hi there",
        gateway_completion=CompletionResponse(
            content="Hi there!", model="m", provider="test", usage=TokenUsage()
        ),
    ),
    MultiAgentScenario(
        name="calculation_routes_to_analyst_only",
        message="What is 15% of 500?",
        expected_status="completed",
        expected_agents_used={"analyst"},
        expect_answer_contains="75",
    ),
    MultiAgentScenario(
        name="research_with_evidence_propagates_context_to_the_answer",
        message="What does the travel policy say about hotel reimbursement?",
        expected_status="completed",
        expected_agents_used={"research"},
        expect_answer_contains="reimbursed up to policy limits",
        retrieval_results=[make_result(content="Hotels are reimbursed up to policy limits.")],
        gateway_completion=CompletionResponse(
            content="Hotels are reimbursed up to policy limits.",
            model="m",
            provider="test",
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        ),
    ),
    MultiAgentScenario(
        name="research_and_document_retain_citation_metadata_through_analyst",
        message="Compare the travel policy with document {document_id}.",
        expected_status="completed",
        expected_agents_used={"research", "document", "analyst"},
        expect_answer_contains="comparison result",
        expect_sources_filename="Policy.pdf",
        retrieval_results=[make_result(content="Policy text.")],
        gateway_completion=CompletionResponse(
            content="The comparison result.", model="m", provider="test", usage=TokenUsage()
        ),
        seed_document=True,
        document_id=SAMPLE_DOCUMENT_ID,
    ),
    MultiAgentScenario(
        name="missing_document_is_a_partial_failure_not_a_crash",
        message="Compare the travel policy with document {document_id}.",
        expected_status="partial",
        expected_agents_used={"research", "document", "analyst"},
        retrieval_results=[make_result(content="Policy text.")],
        gateway_completion=CompletionResponse(
            content="Comparison attempted.", model="m", provider="test", usage=TokenUsage()
        ),
        seed_document=False,
        document_id=uuid.uuid4(),
    ),
]
