"""Unit tests for A2A `Task` construction/serialization: the
completed/failed lifecycle states, the result artifact payload, and that
a failed task carries an error message rather than a fabricated result.
"""

from __future__ import annotations

import uuid

from app.a2a.schemas import ResearchResult, ResearchSource
from app.a2a.tasks import RESEARCH_RESULT_ARTIFACT_NAME, build_task, task_to_dict


def test_completed_task_has_completed_state_and_a_result_artifact() -> None:
    result = ResearchResult(status="completed", answer="The answer.", sources=[])
    task = build_task(question="What is the policy?", result=result)
    payload = task_to_dict(task)

    assert payload["status"]["state"] == "TASK_STATE_COMPLETED"
    assert len(payload["artifacts"]) == 1
    assert payload["artifacts"][0]["name"] == RESEARCH_RESULT_ARTIFACT_NAME


def test_completed_task_artifact_carries_the_answer_and_sources() -> None:
    source = ResearchSource(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="policy.pdf",
        page_number=2,
        similarity=0.91,
    )
    result = ResearchResult(status="completed", answer="The answer.", sources=[source])
    task = build_task(question="q", result=result)
    payload = task_to_dict(task)

    data = payload["artifacts"][0]["parts"][0]["data"]
    assert data["answer"] == "The answer."
    assert len(data["sources"]) == 1
    assert data["sources"][0]["filename"] == "policy.pdf"
    assert data["sources"][0]["chunk_id"] == str(source.chunk_id)


def test_failed_task_has_failed_state_and_no_artifact() -> None:
    result = ResearchResult(status="failed", answer="", error="The language model is unavailable")
    task = build_task(question="q", result=result)
    payload = task_to_dict(task)

    assert payload["status"]["state"] == "TASK_STATE_FAILED"
    assert "artifacts" not in payload or payload["artifacts"] == []


def test_failed_task_status_message_carries_the_error_text() -> None:
    result = ResearchResult(status="failed", answer="", error="The language model is unavailable")
    task = build_task(question="q", result=result)
    payload = task_to_dict(task)

    message_parts = payload["status"]["message"]["parts"]
    assert any(part.get("text") == "The language model is unavailable" for part in message_parts)


def test_task_history_carries_the_original_question() -> None:
    result = ResearchResult(status="completed", answer="a", sources=[])
    task = build_task(question="What is the refund policy?", result=result)
    payload = task_to_dict(task)

    assert payload["history"][0]["role"] == "ROLE_USER"
    assert payload["history"][0]["parts"][0]["text"] == "What is the refund policy?"


def test_each_task_gets_a_unique_id_and_context_id() -> None:
    result = ResearchResult(status="completed", answer="a", sources=[])
    task_one = build_task(question="q", result=result)
    task_two = build_task(question="q", result=result)

    assert task_one.id != task_two.id
    assert task_one.context_id != task_two.context_id
