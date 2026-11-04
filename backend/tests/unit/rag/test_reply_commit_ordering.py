"""M10 review finding M1: the reply and its citations are COMMITTED before the client is told the
reply exists (the streamed final event's `message_id` is followed by `[DONE]`; the JSON answer
carries `message_id`).

`app.db.session.get_session` commits only after the response body has been sent, so the service
commits on its own once the reply and its citations are saved. These tests pin the ordering at the
service (commit after the save, before the generator ends) and at the route (`[DONE]` is produced
only after that commit; a failed commit produces no `[DONE]`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest

from app.api.schemas.rag import RAGChatRequest
from app.api.v1.rag import rag_chat_stream
from app.llm.exceptions import LLMTimeoutError
from app.llm.schemas import ModelRole, StreamChunk
from app.rag.schemas import RAGStreamItem

from .doubles import FakeCitationRepository, FakeRetrievalStrategy, ScriptedRAGGateway, make_result
from .test_rag_service import make_completion, make_service


def _snapshot_on_commit(service: Any, messages: Any, session: Any) -> list[dict[str, Any]]:
    """Records, at each commit, which roles are saved and how many citation rows exist."""
    snapshots: list[dict[str, Any]] = []
    citations = cast(FakeCitationRepository, service._citations)

    def take() -> None:
        snapshots.append(
            {
                "roles": [m.role.value for m in messages.messages],
                "citations": sum(len(rows) for rows in citations.saved.values()),
            }
        )

    session.on_commit = take
    return snapshots


# -- service -----------------------------------------------------------------------------------


async def test_the_stream_commits_after_saving_the_reply_and_before_it_ends() -> None:
    chunks = [StreamChunk(delta="Answer "), StreamChunk(delta="[S1].", is_final=True)]
    service, _c, messages, session = make_service(
        gateway=ScriptedRAGGateway(stream_chunks=chunks),
        strategy=FakeRetrievalStrategy(results=[make_result()]),
    )
    snapshots = _snapshot_on_commit(service, messages, session)

    stream = service.answer_stream(
        conversation_id=None, message="question", model_role=ModelRole.PRIMARY
    )
    commits_seen_with_each_item = []
    async for item in stream:
        commits_seen_with_each_item.append((item.chunk.is_final, session.commit_calls))

    # Nothing is committed while chunks (including the final one) are being yielded ...
    assert commits_seen_with_each_item == [(False, 0), (True, 0)]
    # ... and exactly once before the generator ends, with the reply and its citation saved.
    assert session.commit_calls == 1
    assert snapshots == [{"roles": ["user", "assistant"], "citations": 1}]
    assert session.rollback_calls == 0


async def test_the_no_context_stream_commits_before_yielding_its_message_id() -> None:
    service, _c, messages, session = make_service(
        gateway=ScriptedRAGGateway(), strategy=FakeRetrievalStrategy(results=[])
    )
    snapshots = _snapshot_on_commit(service, messages, session)

    items = [
        (item.message_id, session.commit_calls)
        async for item in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        )
    ]

    ((message_id, commits_when_yielded),) = items
    assert message_id == messages.messages[-1].id
    assert commits_when_yielded == 1
    assert snapshots == [{"roles": ["user", "assistant"], "citations": 0}]


async def test_the_json_answer_is_committed_before_it_is_returned() -> None:
    service, _c, messages, session = make_service(
        gateway=ScriptedRAGGateway(completion=make_completion(content="Yes [S1].")),
        strategy=FakeRetrievalStrategy(results=[make_result()]),
    )
    snapshots = _snapshot_on_commit(service, messages, session)

    answer = await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert answer.message_id == messages.messages[-1].id
    assert snapshots == [{"roles": ["user", "assistant"], "citations": 1}]


async def test_the_no_context_json_answer_is_committed_before_it_is_returned() -> None:
    service, _c, messages, session = make_service(
        gateway=ScriptedRAGGateway(), strategy=FakeRetrievalStrategy(results=[])
    )
    snapshots = _snapshot_on_commit(service, messages, session)

    await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert snapshots == [{"roles": ["user", "assistant"], "citations": 0}]


async def test_a_model_failure_mid_stream_still_rolls_back_and_never_commits() -> None:
    gateway = ScriptedRAGGateway(
        stream_chunks=[StreamChunk(delta="partial")], stream_error=LLMTimeoutError("slow")
    )
    service, _c, _m, session = make_service(
        gateway=gateway, strategy=FakeRetrievalStrategy(results=[make_result()])
    )

    with pytest.raises(LLMTimeoutError):
        async for _item in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        ):
            pass

    assert session.rollback_calls == 1
    assert session.commit_calls == 0


async def test_a_failed_commit_ends_the_stream_with_the_error() -> None:
    chunks = [StreamChunk(delta="Answer [S1].", is_final=True)]
    service, _c, _m, session = make_service(
        gateway=ScriptedRAGGateway(stream_chunks=chunks),
        strategy=FakeRetrievalStrategy(results=[make_result()]),
    )
    session.commit_error = RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        async for _item in service.answer_stream(
            conversation_id=None, message="q", model_role=ModelRole.PRIMARY
        ):
            pass


# -- route ---------------------------------------------------------------------------------------


class _OrderedService:
    """A stand-in for `RAGService.answer_stream` that logs when its commit happens."""

    def __init__(self, log: list[str], *, fail_commit: bool = False) -> None:
        self._log = log
        self._fail_commit = fail_commit

    async def answer_stream(self, **_kwargs: Any) -> AsyncIterator[RAGStreamItem]:
        conversation_id, message_id = uuid.uuid4(), uuid.uuid4()
        yield RAGStreamItem(conversation_id, StreamChunk(delta="Hi "), None, None, None)
        yield RAGStreamItem(
            conversation_id, StreamChunk(delta="there.", is_final=True), [], (), message_id
        )
        self._log.append("saved")
        if self._fail_commit:
            raise RuntimeError("commit failed")
        self._log.append("committed")


async def _events(service: Any) -> AsyncIterator[str]:
    response = await rag_chat_stream(RAGChatRequest(message="hello"), service)
    async for event in response.body_iterator:
        yield event if isinstance(event, str) else bytes(event).decode()


async def test_done_is_sent_only_after_the_reply_is_committed() -> None:
    log: list[str] = []
    seen: list[tuple[str, list[str]]] = []
    async for event in _events(_OrderedService(log)):
        seen.append(("done" if "[DONE]" in event else "data", list(log)))

    assert [kind for kind, _ in seen] == ["data", "data", "done"]
    # When the final data event went out nothing was saved yet; [DONE] came after the commit.
    assert seen[1][1] == []
    assert seen[2][1] == ["saved", "committed"]


async def test_a_failed_commit_sends_no_done() -> None:
    log: list[str] = []
    events: list[str] = []
    with pytest.raises(RuntimeError, match="commit failed"):
        async for event in _events(_OrderedService(log, fail_commit=True)):
            events.append(event)

    assert not any("[DONE]" in event for event in events)
    assert log == ["saved"]
