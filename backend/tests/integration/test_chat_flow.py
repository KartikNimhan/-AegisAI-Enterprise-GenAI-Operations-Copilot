"""End-to-end integration tests: real HTTP + real PostgreSQL persistence,
with a fake `LLMGateway` (no real Groq API call / API key needed).

Uses httpx.AsyncClient (not the sync TestClient) so the request runs on the
same event loop as this test and the `db_session` fixture — the sync
TestClient drives the ASGI app from a separate internal loop/thread, which
would reuse the module-level async engine's pooled connections across event
loops and fail (the same issue documented in
backend/tests/integration/test_readiness_endpoint.py from Milestone 1).

Two session-handling modes are used deliberately:

- Most tests override `get_session` with the shared, rollback-isolated
  `db_session` fixture (see conftest.py) so nothing they do is durable.
- `test_failed_turn_is_fully_rolled_back` instead exercises the *real*
  `get_session` dependency (no override), because it specifically verifies
  that dependency's commit/rollback behavior — the thing that makes a
  failed chat turn atomic in production. Using the test-only override there
  would test nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.conversation_repository import ConversationRepository
from app.db.session import get_session
from app.domain.models.conversation import Conversation
from app.domain.models.message import Message
from app.llm.exceptions import LLMTimeoutError
from app.llm.gateway import get_llm_gateway
from app.llm.schemas import CompletionResponse, StreamChunk, TokenUsage
from app.main import app

from ..unit.services.doubles import ScriptedChatGateway

pytestmark = pytest.mark.integration


@pytest.fixture
async def client_with_db(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def override_gateway() -> Iterator[Any]:
    def _override(fake_gateway: Any) -> None:
        app.dependency_overrides[get_llm_gateway] = lambda: fake_gateway

    yield _override
    app.dependency_overrides.pop(get_llm_gateway, None)


def make_completion(**overrides: object) -> CompletionResponse:
    defaults: dict[str, object] = {
        "content": "Hello back",
        "model": "openai/gpt-oss-120b",
        "provider": "groq",
        "finish_reason": "stop",
        "usage": TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        "request_id": "req_1",
    }
    defaults.update(overrides)
    return CompletionResponse(**defaults)  # type: ignore[arg-type]


async def test_new_conversation_chat_persists_to_database(
    client_with_db: AsyncClient, override_gateway: Any, db_session: AsyncSession
) -> None:
    override_gateway(ScriptedChatGateway(completion=make_completion()))

    response = await client_with_db.post(
        "/api/v1/chat/completions", json={"message": "Explain RAG", "model_role": "primary"}
    )

    assert response.status_code == 200
    body = response.json()
    conversation_id = uuid.UUID(body["conversation_id"])

    result = await db_session.execute(
        select(Message).where(Message.conversation_id == conversation_id)
    )
    stored = result.scalars().all()
    assert sorted(m.content for m in stored) == ["Explain RAG", "Hello back"]

    conversation = await db_session.get(Conversation, conversation_id)
    assert conversation is not None
    assert conversation.title == "Explain RAG"


async def test_existing_conversation_chat_continues_history(
    client_with_db: AsyncClient, override_gateway: Any
) -> None:
    gateway = ScriptedChatGateway(completion=make_completion())
    override_gateway(gateway)

    first_response = await client_with_db.post(
        "/api/v1/chat/completions", json={"message": "first", "model_role": "primary"}
    )
    first = first_response.json()

    await client_with_db.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": first["conversation_id"],
            "message": "second",
            "model_role": "primary",
        },
    )

    second_prompt = gateway.chat_completion_calls[1]
    assert [m.content for m in second_prompt][1:] == ["first", "Hello back", "second"]


async def test_conversation_retrieval_returns_persisted_messages(
    client_with_db: AsyncClient, override_gateway: Any
) -> None:
    override_gateway(ScriptedChatGateway(completion=make_completion()))

    created_response = await client_with_db.post(
        "/api/v1/chat/completions", json={"message": "hi", "model_role": "primary"}
    )
    created = created_response.json()

    detail_response = await client_with_db.get(
        f"/api/v1/conversations/{created['conversation_id']}"
    )
    detail = detail_response.json()

    assert [m["content"] for m in detail["messages"]] == ["hi", "Hello back"]
    assert detail["messages"][1]["total_tokens"] == 15

    listing_response = await client_with_db.get("/api/v1/conversations")
    listing = listing_response.json()
    assert any(c["id"] == created["conversation_id"] for c in listing)


async def test_conversation_deletion_removes_it(
    client_with_db: AsyncClient, override_gateway: Any
) -> None:
    override_gateway(ScriptedChatGateway(completion=make_completion()))
    created_response = await client_with_db.post(
        "/api/v1/chat/completions", json={"message": "hi", "model_role": "primary"}
    )
    created = created_response.json()

    delete_response = await client_with_db.delete(
        f"/api/v1/conversations/{created['conversation_id']}"
    )
    get_response = await client_with_db.get(f"/api/v1/conversations/{created['conversation_id']}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


async def test_streaming_chat_persists_accumulated_response(
    client_with_db: AsyncClient, override_gateway: Any, db_session: AsyncSession
) -> None:
    override_gateway(
        ScriptedChatGateway(
            stream_chunks=[
                StreamChunk(delta="Hel"),
                StreamChunk(
                    delta="lo",
                    finish_reason="stop",
                    is_final=True,
                    model="openai/gpt-oss-20b",
                    usage=TokenUsage(input_tokens=3, output_tokens=2, total_tokens=5),
                ),
            ]
        )
    )

    async with client_with_db.stream(
        "POST",
        "/api/v1/chat/completions/stream",
        json={"message": "hi", "model_role": "fast"},
    ) as response:
        body = b"".join([chunk async for chunk in response.aiter_bytes()]).decode()

    assert "[DONE]" in body

    result = await db_session.execute(select(Message).order_by(Message.created_at))
    stored = result.scalars().all()
    assert [m.content for m in stored] == ["hi", "Hello"]
    assert stored[1].total_tokens == 5


async def test_failed_turn_is_fully_rolled_back(db_session: AsyncSession) -> None:
    """Uses the REAL get_session dependency (no override) for the request
    itself, to verify a failed turn leaves no trace — the atomic-turn
    guarantee this milestone relies on. `db_session` is used only for its
    skip-if-unreachable check and for the post-request verification query
    (a separate connection from the one the request used internally;
    nothing here needs them to be the same connection).
    """
    app.dependency_overrides[get_llm_gateway] = lambda: ScriptedChatGateway(
        completion_error=LLMTimeoutError("timed out", provider="groq")
    )
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/chat/completions", json={"message": "this will fail"}
            )
    finally:
        app.dependency_overrides.pop(get_llm_gateway, None)

    assert response.status_code == 504

    repo = ConversationRepository(db_session)
    remaining = await repo.list(limit=50)
    assert not any(c.title == "this will fail" for c in remaining)
