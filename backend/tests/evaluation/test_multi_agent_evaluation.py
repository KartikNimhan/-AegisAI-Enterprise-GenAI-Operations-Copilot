"""Runs the deterministic multi-agent evaluation fixture
(multi_agent_fixtures.py) against the real `MultiAgentOrchestrator`
through the real `POST /api/v1/multi-agent/run` endpoint — reusing
`tests/unit/multi_agent/conftest.py`'s `orchestrator_env`/`async_client`
fixtures exactly as `tests/unit/multi_agent/test_orchestrator.py` does.
No real LLM, DB, or network call. See multi_agent_fixtures.py's module
docstring for why this exists alongside that already-thorough suite.
"""

from __future__ import annotations

from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType
from app.domain.models.document import Document

from .multi_agent_fixtures import SCENARIOS, MultiAgentScenario


def _make_document(document_id) -> Document:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return Document(
        id=document_id,
        filename="internal.pdf",
        original_filename="Policy.pdf",
        content_type="application/pdf",
        document_type=DocumentType.PDF,
        file_size=10,
        checksum="a" * 64,
        status=DocumentStatus.PROCESSED,
        page_count=3,
        character_count=100,
        created_at=now,
        updated_at=now,
    )


async def _run_scenario(
    scenario: MultiAgentScenario, *, async_client, orchestrator_env, fake_documents
) -> list[str]:
    """Returns a list of human-readable failure descriptions — empty if
    the scenario behaved as designed."""
    failures: list[str] = []

    if scenario.gateway_completion is not None:
        from ..unit.rag.doubles import ScriptedRAGGateway

        orchestrator_env["gateway"] = ScriptedRAGGateway(completion=scenario.gateway_completion)
    if scenario.retrieval_results is not None:
        orchestrator_env["retrieval_results"] = scenario.retrieval_results

    message = scenario.message
    if scenario.document_id is not None:
        if scenario.seed_document:
            fake_documents.documents[scenario.document_id] = _make_document(scenario.document_id)
        message = message.format(document_id=scenario.document_id)

    response = await async_client.post("/api/v1/multi-agent/run", json={"message": message})
    if response.status_code != 200:
        return [f"HTTP {response.status_code}: {response.text}"]
    payload = response.json()

    if payload["status"] != scenario.expected_status:
        failures.append(f"status={payload['status']!r} expected={scenario.expected_status!r}")

    actual_agents = {a["agent_name"] for a in payload.get("agents_used", [])}
    if actual_agents != scenario.expected_agents_used:
        failures.append(f"agents={actual_agents!r} expected={scenario.expected_agents_used!r}")

    if (
        scenario.expect_answer_contains is not None
        and scenario.expect_answer_contains.lower() not in payload.get("answer", "").lower()
    ):
        failures.append(
            f"answer={payload.get('answer')!r} missing {scenario.expect_answer_contains!r}"
        )

    if scenario.expect_sources_filename is not None:
        sources = payload.get("sources") or []
        if not any(s.get("filename") == scenario.expect_sources_filename for s in sources):
            failures.append(
                f"sources={sources!r} missing filename {scenario.expect_sources_filename!r} — "
                "citation metadata did not survive the tier1 -> analyst handoff"
            )

    return failures


async def test_multi_agent_evaluation_fixture(
    async_client, orchestrator_env, fake_documents
) -> None:
    results: list[tuple[str, bool, str]] = []

    for scenario in SCENARIOS:
        failures = await _run_scenario(
            scenario,
            async_client=async_client,
            orchestrator_env=orchestrator_env,
            fake_documents=fake_documents,
        )
        passed = not failures
        results.append((scenario.name, passed, "; ".join(failures)))

    pass_count = sum(1 for _name, passed, _detail in results if passed)
    total = len(results)
    print(f"\nMulti-agent evaluation: {pass_count}/{total} scenarios behaved as designed")
    for name, passed, detail in results:
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {name}" + (f" ({detail})" if detail else ""))

    failing = [name for name, passed, _detail in results if not passed]
    assert not failing, f"Scenarios that did not behave as designed: {failing}"
