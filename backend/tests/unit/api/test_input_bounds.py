"""Request bounds: blank and oversized input is rejected at the schema, before any model call."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.api.schemas.agents import AgentRunRequest
from app.api.schemas.chat import ChatCompletionRequest
from app.api.schemas.multi_agent import MultiAgentRunRequest
from app.api.schemas.rag import RAGChatRequest
from app.api.v1.analyst_agent import AnalystTaskRequest
from app.api.v1.document_agent import DocumentTaskRequest
from app.api.v1.research_agent import ResearchTaskRequest
from app.core.limits import (
    MAX_EVIDENCE_CHARS,
    MAX_EVIDENCE_ITEMS,
    MAX_EXPRESSION_CHARS,
    MAX_EXPRESSIONS,
    MAX_MESSAGE_CHARS,
    MAX_TASK_ITEMS,
)

MESSAGE_MODELS = [ChatCompletionRequest, RAGChatRequest, AgentRunRequest, MultiAgentRunRequest]


@pytest.mark.parametrize("model", MESSAGE_MODELS)
def test_message_is_trimmed_and_bounded(model: type) -> None:
    assert model(message="  hello \n").message == "hello"
    assert model(message="x" * MAX_MESSAGE_CHARS).message
    for bad in ("", "   \n\t ", "x" * (MAX_MESSAGE_CHARS + 1)):
        with pytest.raises(ValidationError):
            model(message=bad)


def test_research_question_is_bounded() -> None:
    assert ResearchTaskRequest(question=" q ").question == "q"
    for bad in ("  ", "x" * (MAX_MESSAGE_CHARS + 1)):
        with pytest.raises(ValidationError):
            ResearchTaskRequest(question=bad)


def test_document_task_id_count_is_capped() -> None:
    ids = [str(uuid.uuid4()) for _ in range(MAX_TASK_ITEMS + 1)]
    with pytest.raises(ValidationError):
        DocumentTaskRequest(document_ids=ids)  # type: ignore[arg-type]
    assert DocumentTaskRequest(document_ids=ids[:MAX_TASK_ITEMS])  # type: ignore[arg-type]


def test_analyst_lists_and_texts_are_capped() -> None:
    with pytest.raises(ValidationError):
        AnalystTaskRequest(expressions=["1+1"] * (MAX_EXPRESSIONS + 1))
    with pytest.raises(ValidationError):
        AnalystTaskRequest(expressions=["1" * (MAX_EXPRESSION_CHARS + 1)])
    with pytest.raises(ValidationError):
        AnalystTaskRequest(evidence=["e"] * (MAX_EVIDENCE_ITEMS + 1))
    with pytest.raises(ValidationError):
        AnalystTaskRequest(evidence=["e" * (MAX_EVIDENCE_CHARS + 1)])
    with pytest.raises(ValidationError):
        AnalystTaskRequest(question="x" * (MAX_MESSAGE_CHARS + 1))
    assert AnalystTaskRequest().question == ""
    assert AnalystTaskRequest(expressions=["2*3"], evidence=["fact"])


def test_oversized_message_gets_422_over_http() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).post(
        "/api/v1/chat/completions", json={"message": "x" * (MAX_MESSAGE_CHARS + 1)}
    )
    assert response.status_code == 422
