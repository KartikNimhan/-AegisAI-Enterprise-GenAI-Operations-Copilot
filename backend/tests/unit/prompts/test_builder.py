"""Unit tests for PromptBuilder: message structure and role mapping."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.enums.message_role import MessageRole
from app.domain.models.message import Message
from app.llm.schemas import ChatRole
from app.prompts.builder import PromptBuilder
from app.prompts.templates import AEGIS_CHAT_SYSTEM_PROMPT


def make_message(role: MessageRole, content: str) -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role=role,
        content=content,
        created_at=datetime.now(UTC),
    )


def test_build_with_no_history_returns_system_then_user() -> None:
    builder = PromptBuilder()

    result = builder.build(history=[], user_message="Hello")

    assert [(m.role, m.content) for m in result] == [
        (ChatRole.SYSTEM, AEGIS_CHAT_SYSTEM_PROMPT.text),
        (ChatRole.USER, "Hello"),
    ]


def test_build_with_history_preserves_order_and_maps_roles() -> None:
    builder = PromptBuilder()
    history = [
        make_message(MessageRole.USER, "first question"),
        make_message(MessageRole.ASSISTANT, "first answer"),
    ]

    result = builder.build(history=history, user_message="second question")

    assert [(m.role, m.content) for m in result] == [
        (ChatRole.SYSTEM, AEGIS_CHAT_SYSTEM_PROMPT.text),
        (ChatRole.USER, "first question"),
        (ChatRole.ASSISTANT, "first answer"),
        (ChatRole.USER, "second question"),
    ]


def test_build_uses_configured_system_prompt() -> None:
    from app.prompts.schemas import PromptTemplate

    custom_prompt = PromptTemplate(id="custom", version=1, text="Custom system text")
    builder = PromptBuilder(system_prompt=custom_prompt)

    result = builder.build(history=[], user_message="hi")

    assert result[0].content == "Custom system text"
