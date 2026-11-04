"""The output guard on every answer path (AIGSEC-015): chat, RAG and agent answers, streamed and
not, what is stored, tool results before the model sees them, and an A2A specialist's answer.
Models are scripted; nothing is sent to a provider.

Fake credentials are assembled at runtime (see test_output_guard.py).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.a2a.analyst_agent import AnalystAgentService
from app.a2a.schemas import AnalystAgentResult
from app.agents.service import AgentService
from app.agents.tools.registry import build_tool_registry
from app.api.v1.analyst_agent import get_analyst_agent_service
from app.config import Settings
from app.llm.schemas import ChatRole, ModelRole, StreamChunk, TokenUsage
from app.main import app
from app.rag.retrieval.service import RetrievalService

from ..agents.doubles import ScriptedAgentGateway, make_final_completion, make_tool_call_completion
from ..rag.doubles import FakeRetrievalStrategy, ScriptedRAGGateway, make_result
from ..rag.test_rag_service import make_completion as make_rag_completion
from ..rag.test_rag_service import make_service as make_rag_service
from ..services.document_doubles import FakeDocumentRepository
from ..services.doubles import (
    FakeConversationRepository,
    FakeMessageRepository,
    FakeSession,
    ScriptedChatGateway,
)
from ..services.test_chat_service import make_completion as make_chat_completion
from ..services.test_chat_service import make_service as make_chat_service

SECRET = "gsk" + "_" + "Ab3" * 12


def _chunks(text: str, size: int = 4) -> list[StreamChunk]:
    parts = [text[i : i + size] for i in range(0, len(text), size)]
    chunks = [StreamChunk(delta=part) for part in parts[:-1]]
    chunks.append(
        StreamChunk(
            delta=parts[-1],
            is_final=True,
            finish_reason="stop",
            model="m",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )
    )
    return chunks


# -- chat ---------------------------------------------------------------------------------------


async def test_a_chat_answer_is_returned_and_stored_redacted() -> None:
    gateway = ScriptedChatGateway(completion=make_chat_completion(content=f"Use {SECRET} now."))
    service, _, messages, _ = make_chat_service(gateway)

    result = await service.send_message(
        conversation_id=None, message="hi", model_role=ModelRole.FAST
    )

    assert result.response.content == "Use [REDACTED:credential] now."
    assert messages.messages[-1].content == "Use [REDACTED:credential] now."


async def test_a_streamed_chat_answer_never_sends_the_secret_and_stores_what_was_sent() -> None:
    text = f"The key is {SECRET} so keep it safe."
    service, _, messages, _ = make_chat_service(ScriptedChatGateway(stream_chunks=_chunks(text)))

    deltas = [
        c.chunk.delta
        async for c in service.stream_message(
            conversation_id=None, message="hi", model_role=ModelRole.FAST
        )
    ]

    sent = "".join(deltas)
    assert SECRET[:8] not in sent
    assert sent == "The key is [REDACTED:credential] so keep it safe."
    assert messages.messages[-1].content == sent  # final and streamed are the same


# -- RAG ----------------------------------------------------------------------------------------


async def test_a_rag_answer_is_redacted_and_its_citations_still_checked() -> None:
    gateway = ScriptedRAGGateway(
        completion=make_rag_completion(content=f"The admin key is {SECRET} [S1] [S9].")
    )
    strategy = FakeRetrievalStrategy(results=[make_result(content="internal notes")])
    service, _, messages, _ = make_rag_service(gateway=gateway, strategy=strategy)

    answer = await service.answer(conversation_id=None, message="key?", model_role=ModelRole.FAST)

    assert SECRET not in answer.answer
    assert "[REDACTED:credential]" in answer.answer
    assert "[S1]" in answer.answer and "S9" not in answer.answer  # S9 was never retrieved
    assert answer.invalid_citations == ("S9",)
    assert messages.messages[-1].content == answer.answer


async def test_a_streamed_rag_answer_matches_the_stored_one_and_never_leaks() -> None:
    text = f"Use {SECRET} as described [S1]. Done."
    gateway = ScriptedRAGGateway(stream_chunks=_chunks(text, size=3))
    strategy = FakeRetrievalStrategy(results=[make_result(content="internal notes")])
    service, _, messages, _ = make_rag_service(gateway=gateway, strategy=strategy)

    deltas = [
        chunk.delta
        async for _id, chunk, _sources, _invalid, _mid in service.answer_stream(
            conversation_id=None, message="key?", model_role=ModelRole.FAST
        )
    ]

    sent = "".join(deltas)
    assert SECRET[:8] not in sent
    assert sent == "Use [REDACTED:credential] as described [S1]. Done."
    assert messages.messages[-1].content == sent


# -- agents -------------------------------------------------------------------------------------


async def _agent(gateway: ScriptedAgentGateway, retrieved: str) -> AgentService:
    settings = Settings(agent_timeout_seconds=5.0)
    registry = await build_tool_registry(
        documents=FakeDocumentRepository(),  # type: ignore[arg-type]
        retrieval=RetrievalService(
            strategy=FakeRetrievalStrategy(results=[make_result(content=retrieved)]),
            settings=settings,
        ),
        settings=settings,
    )
    return AgentService(
        session=FakeSession(),  # type: ignore[arg-type]
        settings=settings,
        gateway=gateway,
        conversations=FakeConversationRepository(),  # type: ignore[arg-type]
        messages=FakeMessageRepository(),  # type: ignore[arg-type]
        tool_registry=registry,
    )


async def test_a_tool_result_is_redacted_before_the_model_sees_it() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="search_knowledge_base", arguments={"query": "k"}),
            make_final_completion("Found it."),
        ]
    )
    agent = await _agent(gateway, retrieved=f"The deploy key is {SECRET} (do not share).")

    await agent.run(conversation_id=None, message="Find the deploy key")

    tool_messages = [
        m for m in gateway.chat_completion_calls[1]["messages"] if m.role == ChatRole.TOOL
    ]
    (tool_message,) = tool_messages
    assert SECRET not in tool_message.content
    payload = json.loads(tool_message.content)  # still valid JSON with the same structure
    assert payload["success"] is True
    assert "[REDACTED:credential]" in json.dumps(payload["data"])


async def test_an_agent_answer_is_returned_and_stored_redacted() -> None:
    gateway = ScriptedAgentGateway(effects=[make_final_completion(f"It is {SECRET}.")])
    agent = await _agent(gateway, retrieved="nothing")

    result = await agent.run(conversation_id=None, message="key?")

    assert result.answer == "It is [REDACTED:credential]."
    stored = agent._messages.messages[-1].content  # type: ignore[attr-defined]
    assert stored == result.answer


async def test_a_streamed_agent_answer_is_redacted_too() -> None:
    gateway = ScriptedAgentGateway(effects=[make_final_completion(f"It is {SECRET}.")])
    agent = await _agent(gateway, retrieved="nothing")

    events = [event async for _cid, event in agent.run_stream(conversation_id=None, message="k")]

    sent = json.dumps([event.data for event in events])
    assert SECRET not in sent
    assert "[REDACTED:credential]" in sent


# -- an A2A specialist -------------------------------------------------------------------------


class _LeakyAnalyst(AnalystAgentService):
    def __init__(self) -> None:
        pass

    async def analyze(self, **_kwargs: Any) -> AnalystAgentResult:
        return AnalystAgentResult(status="completed", answer=f"Summary: {SECRET}")


@pytest.fixture
def leaky_analyst() -> Iterator[None]:
    app.dependency_overrides[get_analyst_agent_service] = lambda: _LeakyAnalyst()
    yield
    app.dependency_overrides.pop(get_analyst_agent_service, None)


def test_an_a2a_specialists_answer_is_redacted_before_it_leaves(
    client: TestClient, leaky_analyst: None
) -> None:
    response = client.post(
        "/api/v1/agents/analyst/tasks", json={"question": "q", "evidence": ["e"]}
    )

    assert response.status_code == 200
    assert SECRET not in response.text
    assert "[REDACTED:credential]" in response.text
