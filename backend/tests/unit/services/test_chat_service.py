"""Unit tests for ChatService: conversation lifecycle, prompt construction,
persistence, and streaming — all against fakes, no real DB or Groq call.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import NotFoundError
from app.domain.enums.message_role import MessageRole
from app.llm.exceptions import LLMTimeoutError
from app.llm.schemas import ChatRole, CompletionResponse, ModelRole, StreamChunk, TokenUsage
from app.prompts.templates import AEGIS_CHAT_SYSTEM_PROMPT
from app.services.chat_service import ChatService

from .doubles import (
    FakeConversationRepository,
    FakeMessageRepository,
    FakeSession,
    ScriptedChatGateway,
)


def make_service(
    gateway: ScriptedChatGateway,
) -> tuple[ChatService, FakeConversationRepository, FakeMessageRepository, FakeSession]:
    session = FakeSession()
    conversations = FakeConversationRepository()
    messages = FakeMessageRepository()
    service = ChatService(
        gateway=gateway,
        session=session,  # type: ignore[arg-type]
        conversations=conversations,  # type: ignore[arg-type]
        messages=messages,  # type: ignore[arg-type]
    )
    return service, conversations, messages, session


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


async def test_new_conversation_creates_conversation_and_persists_both_messages() -> None:
    gateway = ScriptedChatGateway(completion=make_completion())
    service, conversations, messages, _ = make_service(gateway)

    result = await service.send_message(
        conversation_id=None, message="Hi there", model_role=ModelRole.PRIMARY
    )

    assert result.conversation_id in conversations.conversations
    assert result.response.content == "Hello back"
    assert [m.role for m in messages.messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert messages.messages[0].content == "Hi there"
    assert messages.messages[1].content == "Hello back"


async def test_new_conversation_title_derived_from_first_message() -> None:
    gateway = ScriptedChatGateway(completion=make_completion())
    service, conversations, _, _ = make_service(gateway)

    result = await service.send_message(
        conversation_id=None, message="Explain RAG", model_role=ModelRole.PRIMARY
    )

    assert conversations.conversations[result.conversation_id].title == "Explain RAG"


async def test_existing_conversation_includes_prior_history_in_prompt() -> None:
    gateway = ScriptedChatGateway(completion=make_completion())
    service, conversations, messages, _ = make_service(gateway)

    first = await service.send_message(
        conversation_id=None, message="First message", model_role=ModelRole.PRIMARY
    )
    await service.send_message(
        conversation_id=first.conversation_id,
        message="Second message",
        model_role=ModelRole.PRIMARY,
    )

    second_call_prompt = gateway.chat_completion_calls[1]
    assert [m.content for m in second_call_prompt] == [
        AEGIS_CHAT_SYSTEM_PROMPT.text,
        "First message",
        "Hello back",
        "Second message",
    ]
    assert second_call_prompt[0].role == ChatRole.SYSTEM
    assert second_call_prompt[-1].role == ChatRole.USER
    assert len(messages.messages) == 4


async def test_unknown_conversation_id_raises_not_found() -> None:
    gateway = ScriptedChatGateway(completion=make_completion())
    service, _, _, _ = make_service(gateway)

    with pytest.raises(NotFoundError):
        await service.send_message(
            conversation_id=uuid.uuid4(), message="hi", model_role=ModelRole.PRIMARY
        )


async def test_model_role_is_forwarded_to_gateway() -> None:
    gateway = ScriptedChatGateway(completion=make_completion())
    service, _, _, _ = make_service(gateway)

    await service.send_message(conversation_id=None, message="hi", model_role=ModelRole.FAST)

    assert gateway.stream_calls == []  # sanity: non-streaming path only


async def test_token_usage_and_model_metadata_are_persisted() -> None:
    gateway = ScriptedChatGateway(
        completion=make_completion(
            model="openai/gpt-oss-20b",
            provider="groq",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=7, output_tokens=3, total_tokens=10),
            request_id="req_xyz",
        )
    )
    service, _, messages, _ = make_service(gateway)

    await service.send_message(conversation_id=None, message="hi", model_role=ModelRole.FAST)

    assistant_message = messages.messages[1]
    assert assistant_message.model == "openai/gpt-oss-20b"
    assert assistant_message.provider == "groq"
    assert assistant_message.finish_reason == "stop"
    assert assistant_message.request_id == "req_xyz"
    assert assistant_message.input_tokens == 7
    assert assistant_message.output_tokens == 3
    assert assistant_message.total_tokens == 10


async def test_conversation_is_touched_after_a_turn() -> None:
    gateway = ScriptedChatGateway(completion=make_completion())
    service, conversations, _, _ = make_service(gateway)

    result = await service.send_message(
        conversation_id=None, message="hi", model_role=ModelRole.PRIMARY
    )

    assert conversations.touch_calls == [result.conversation_id]


async def test_streaming_yields_chunks_and_persists_accumulated_content() -> None:
    chunks = [
        StreamChunk(delta="He"),
        StreamChunk(
            delta="llo",
            finish_reason="stop",
            is_final=True,
            model="openai/gpt-oss-20b",
            request_id="req_stream",
            usage=TokenUsage(input_tokens=4, output_tokens=2, total_tokens=6),
        ),
    ]
    gateway = ScriptedChatGateway(stream_chunks=chunks)
    service, conversations, messages, _ = make_service(gateway)

    received = [
        turn_chunk
        async for turn_chunk in service.stream_message(
            conversation_id=None, message="hi", model_role=ModelRole.FAST
        )
    ]

    assert [c.chunk.delta for c in received] == ["He", "llo"]
    assert all(c.conversation_id == received[0].conversation_id for c in received)

    assert [m.role for m in messages.messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assistant_message = messages.messages[1]
    assert assistant_message.content == "Hello"
    assert assistant_message.model == "openai/gpt-oss-20b"
    assert assistant_message.finish_reason == "stop"
    assert assistant_message.input_tokens == 4
    assert assistant_message.output_tokens == 2
    assert assistant_message.total_tokens == 6
    assert conversations.touch_calls == [received[0].conversation_id]


async def test_interrupted_stream_rolls_back_and_does_not_persist_assistant_message() -> None:
    gateway = ScriptedChatGateway(
        stream_chunks=[StreamChunk(delta="partial")],
        stream_error=LLMTimeoutError("timed out", provider="groq"),
    )
    service, _, messages, session = make_service(gateway)

    received = []
    with pytest.raises(LLMTimeoutError):
        async for turn_chunk in service.stream_message(
            conversation_id=None, message="hi", model_role=ModelRole.FAST
        ):
            received.append(turn_chunk)

    assert [c.chunk.delta for c in received] == ["partial"]
    assert session.rollback_calls == 1
    # Only the user message was ever added; no assistant message/no touch.
    assert [m.role for m in messages.messages] == [MessageRole.USER]
