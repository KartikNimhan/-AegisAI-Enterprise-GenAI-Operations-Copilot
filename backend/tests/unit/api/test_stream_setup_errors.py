"""A streaming endpoint must fail like its non-streaming twin when the request cannot start.

Once a StreamingResponse starts, its status is committed, so before this was fixed an unknown
or foreign `conversation_id` produced "HTTP 200, empty body" plus a logged unhandled exception
on all three streaming endpoints. `app.api.streaming.start_stream` runs the generator up to its
first event before the response exists.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.service import get_agent_service
from app.api.streaming import start_stream
from app.core.exceptions import NotFoundError
from app.main import app
from app.rag.service import get_rag_service
from app.services.chat_service import get_chat_service

# -- the helper ------------------------------------------------------------------------


async def _events(*items: str, then: Exception | None = None) -> AsyncIterator[str]:
    for item in items:
        yield item
    if then is not None:
        raise then


async def _collect(stream: AsyncIterator[str]) -> list[str]:
    return [item async for item in stream]


async def test_every_event_passes_through_in_order() -> None:
    assert await _collect(await start_stream(_events("a", "b", "c"))) == ["a", "b", "c"]


async def test_an_empty_stream_is_an_empty_stream() -> None:
    assert await _collect(await start_stream(_events())) == []


async def test_a_failure_before_the_first_event_is_raised_to_the_caller_not_deferred() -> None:
    with pytest.raises(NotFoundError):
        await start_stream(_events(then=NotFoundError("Conversation not found")))


async def test_a_failure_after_the_first_event_surfaces_while_streaming() -> None:
    stream = await start_stream(_events("first", then=RuntimeError("mid-stream")))

    with pytest.raises(RuntimeError, match="mid-stream"):
        await _collect(stream)


# -- the three endpoints ----------------------------------------------------------------


class _Missing:
    """A service whose conversation lookup fails while the stream is being set up."""

    async def stream_message(self, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotFoundError("Conversation not found")
        yield  # pragma: no cover

    async def answer_stream(self, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotFoundError("Conversation not found")
        yield  # pragma: no cover

    async def run_stream(self, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotFoundError("Conversation not found")
        yield  # pragma: no cover


STREAMING_ENDPOINTS = [
    ("/api/v1/chat/completions/stream", get_chat_service),
    ("/api/v1/rag/chat/stream", get_rag_service),
    ("/api/v1/agents/run/stream", get_agent_service),
]


@pytest.fixture
def missing_conversation() -> Iterator[None]:
    for _, dependency in STREAMING_ENDPOINTS:
        app.dependency_overrides[dependency] = lambda: _Missing()
    yield
    for _, dependency in STREAMING_ENDPOINTS:
        app.dependency_overrides.pop(dependency, None)


@pytest.mark.usefixtures("missing_conversation")
@pytest.mark.parametrize(("path", "_dependency"), STREAMING_ENDPOINTS)
def test_an_unknown_or_foreign_conversation_is_a_404_before_streaming_starts(
    client: TestClient, path: str, _dependency: Any
) -> None:
    response = client.post(path, json={"conversation_id": str(uuid.uuid4()), "message": "hi"})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Conversation not found"


class _Streaming:
    """A service that streams two chunks, to prove the happy path is unchanged."""

    async def stream_message(self, **kwargs: Any) -> AsyncIterator[Any]:
        from app.llm.schemas import StreamChunk
        from app.services.chat_service import StreamTurnChunk

        conversation_id = uuid.uuid4()
        yield StreamTurnChunk(conversation_id=conversation_id, chunk=StreamChunk(delta="Hel"))
        yield StreamTurnChunk(
            conversation_id=conversation_id,
            chunk=StreamChunk(delta="lo", finish_reason="stop", is_final=True),
        )


def test_a_normal_stream_still_delivers_every_event_and_the_done_marker(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_chat_service] = lambda: _Streaming()
    try:
        response = client.post("/api/v1/chat/completions/stream", json={"message": "hi"})
    finally:
        app.dependency_overrides.pop(get_chat_service, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    data_lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    assert len(data_lines) == 3 and data_lines[-1] == "data: [DONE]"
    assert '"delta":"Hel"' in data_lines[0] and '"delta":"lo"' in data_lines[1]
