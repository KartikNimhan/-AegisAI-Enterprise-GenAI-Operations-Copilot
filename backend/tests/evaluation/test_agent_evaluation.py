"""Runs the deterministic agent evaluation fixture (agent_fixtures.py)
against the real `AgentService`/LangGraph graph/tool registry, with a
scripted LLM gateway and a fake retrieval strategy — no real DB, model, or
Groq call.

See agent_fixtures.py's module docstring and
docs/architecture/decisions/008-agent-architecture.md, "Evaluation
approach", for why this is a behavioral regression checklist, not a
measurement of real-model accuracy.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.agents.service import AgentService
from app.agents.tools.registry import build_tool_registry
from app.config import Settings
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document
from app.rag.retrieval.service import RetrievalService

from ..unit.agents.doubles import ScriptedAgentGateway
from ..unit.rag.doubles import FakeRetrievalStrategy, make_result
from ..unit.services.document_doubles import FakeDocumentRepository
from ..unit.services.doubles import FakeConversationRepository, FakeMessageRepository, FakeSession
from .agent_fixtures import SAMPLE_DOCUMENT_ID, SCENARIOS, AgentScenario


def _make_settings(scenario: AgentScenario) -> Settings:
    return Settings(
        agent_max_steps=scenario.agent_max_steps or 8,
        agent_max_tool_calls=10,
        agent_timeout_seconds=5.0,
        rag_top_k=5,
        rag_max_results=20,
        rag_similarity_threshold=0.3,
    )


async def _make_service(scenario: AgentScenario) -> tuple[AgentService, ScriptedAgentGateway]:
    settings = _make_settings(scenario)
    results = (
        scenario.retrieval_results if scenario.retrieval_results is not None else [make_result()]
    )
    retrieval = RetrievalService(strategy=FakeRetrievalStrategy(results=results), settings=settings)
    gateway = ScriptedAgentGateway(effects=list(scenario.effects))
    documents = FakeDocumentRepository()
    if scenario.seed_sample_document:
        now = datetime.now(UTC)
        documents.documents[SAMPLE_DOCUMENT_ID] = Document(
            id=SAMPLE_DOCUMENT_ID,
            filename="internal-key.pdf",
            original_filename="Sample.pdf",
            content_type="application/pdf",
            document_type=DocumentType.PDF,
            file_size=100,
            checksum="a" * 64,
            status=DocumentStatus.PROCESSED,
            page_count=3,
            character_count=500,
            created_at=now,
            updated_at=now,
        )
    tool_registry = await build_tool_registry(
        documents=documents,  # type: ignore[arg-type]
        retrieval=retrieval,
        settings=settings,
    )
    service = AgentService(
        session=FakeSession(),  # type: ignore[arg-type]
        settings=settings,
        gateway=gateway,
        conversations=FakeConversationRepository(),  # type: ignore[arg-type]
        messages=FakeMessageRepository(),  # type: ignore[arg-type]
        tool_registry=tool_registry,
    )
    return service, gateway


def _security_invariant_failures(
    scenario: AgentScenario, gateway: ScriptedAgentGateway
) -> list[str]:
    """Every call's first message must be the agent's own system prompt,
    and the raw content of any seeded (possibly malicious) retrieval
    result must never appear inside it — the structural guarantee that
    tool output can never replace or merge into the system prompt."""
    failures: list[str] = []
    malicious_texts = [r.content for r in (scenario.retrieval_results or [])]
    for call in gateway.chat_completion_calls:
        system_message = call["messages"][0]
        if system_message.role.value != "system":
            failures.append("first message in an LLM call was not the system prompt")
            continue
        for text in malicious_texts:
            if text in system_message.content:
                failures.append("retrieval result content leaked into the system message")
    return failures


async def test_agent_evaluation_fixture() -> None:
    results: list[tuple[str, bool, str]] = []

    for scenario in SCENARIOS:
        service, gateway = await _make_service(scenario)
        run_result = await service.run(conversation_id=None, message=scenario.message)

        failures: list[str] = []
        failures.extend(_security_invariant_failures(scenario, gateway))
        if run_result.status != scenario.expected_status:
            failures.append(f"status={run_result.status!r} expected={scenario.expected_status!r}")
        actual_tool_names = {t.name for t in run_result.tool_calls}
        if actual_tool_names != scenario.expected_tool_names:
            failures.append(
                f"tools={actual_tool_names!r} expected={scenario.expected_tool_names!r}"
            )
        if (
            scenario.expect_answer_contains is not None
            and scenario.expect_answer_contains.lower() not in run_result.answer.lower()
        ):
            failures.append(
                f"answer={run_result.answer!r} missing {scenario.expect_answer_contains!r}"
            )

        passed = not failures
        results.append((scenario.name, passed, "; ".join(failures)))

    pass_count = sum(1 for _name, passed, _detail in results if passed)
    total = len(results)
    print(f"\nAgent evaluation: {pass_count}/{total} scenarios behaved as designed")
    for name, passed, detail in results:
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {name}" + (f" ({detail})" if detail else ""))

    failing = [name for name, passed, _detail in results if not passed]
    assert not failing, f"Scenarios that did not behave as designed: {failing}"
