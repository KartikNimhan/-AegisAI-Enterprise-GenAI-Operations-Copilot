"""Opt-in integration test against the real Groq API and the real agent
graph — proves tool selection and execution actually works with a real
model, not just scripted fakes.

Skips automatically when GROQ_API_KEY is not set, mirroring
test_groq_live.py. Uses a fake retrieval strategy (empty results) so this
test exercises tool *selection* (calculator) without also requiring the
real embedding model — that combination is covered separately by
test_rag_pipeline_live.py/test_agent_flow.py.

Validated structurally, not by exact wording: the model chose the
registered `calculator` tool, the tool executed successfully, and the
final answer contains the correct numeric result.

Run explicitly with a real key via:
    GROQ_API_KEY=sk-... uv run pytest -m llm_integration -v
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import STATUS_COMPLETED
from app.agents.service import AgentService
from app.agents.tools.registry import build_tool_registry
from app.config import get_settings
from app.db.repositories.conversation_repository import ConversationRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.message_repository import MessageRepository
from app.llm.gateway import LLMGateway
from app.llm.schemas import ModelRole
from app.rag.retrieval.service import RetrievalService

from ..unit.rag.doubles import FakeRetrievalStrategy

pytestmark = [
    pytest.mark.llm_integration,
    pytest.mark.skipif(
        not os.environ.get("GROQ_API_KEY"),
        reason="GROQ_API_KEY is not set — skipping real Groq agent test",
    ),
]


async def test_real_model_selects_and_executes_the_calculator_tool(
    db_session: AsyncSession,
) -> None:
    settings = get_settings()
    gateway = LLMGateway(settings)
    retrieval = RetrievalService(strategy=FakeRetrievalStrategy(results=[]), settings=settings)
    tool_registry = await build_tool_registry(
        documents=DocumentRepository(db_session), retrieval=retrieval, settings=settings
    )
    service = AgentService(
        session=db_session,
        settings=settings,
        gateway=gateway,
        conversations=ConversationRepository(db_session),
        messages=MessageRepository(db_session),
        tool_registry=tool_registry,
    )

    result = await service.run(
        conversation_id=None,
        message="Use your calculator tool to compute 123 multiplied by 7, then tell me the result.",
        model_role=ModelRole.FAST,
    )

    assert result.status == STATUS_COMPLETED
    assert any(t.name == "calculator" and t.success_count >= 1 for t in result.tool_calls)
    assert "861" in result.answer


async def test_real_model_answers_directly_without_a_tool_when_none_is_needed(
    db_session: AsyncSession,
) -> None:
    settings = get_settings()
    gateway = LLMGateway(settings)
    retrieval = RetrievalService(strategy=FakeRetrievalStrategy(results=[]), settings=settings)
    tool_registry = await build_tool_registry(
        documents=DocumentRepository(db_session), retrieval=retrieval, settings=settings
    )
    service = AgentService(
        session=db_session,
        settings=settings,
        gateway=gateway,
        conversations=ConversationRepository(db_session),
        messages=MessageRepository(db_session),
        tool_registry=tool_registry,
    )

    result = await service.run(
        conversation_id=None,
        message="In one short sentence, what is the capital of France?",
        model_role=ModelRole.FAST,
    )

    assert result.status == STATUS_COMPLETED
    assert result.answer.strip() != ""
    assert "Paris" in result.answer
