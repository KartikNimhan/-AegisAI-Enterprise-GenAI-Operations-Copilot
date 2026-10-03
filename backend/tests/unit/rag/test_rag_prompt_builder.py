"""Unit tests for RAGPromptBuilder: system instructions, context/question
insertion, history ordering, and the untrusted-document framing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.enums.message_role import MessageRole
from app.domain.models.message import Message
from app.llm.schemas import ChatRole
from app.rag.prompts.builder import RAGPromptBuilder
from app.rag.prompts.templates import AEGIS_RAG_SYSTEM_PROMPT


def make_message(role: MessageRole, content: str) -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role=role,
        content=content,
        created_at=datetime.now(UTC),
    )


def test_first_message_is_the_rag_system_prompt() -> None:
    builder = RAGPromptBuilder()

    messages = builder.build(context_text="some context", question="a question?", history=[])

    assert messages[0].role == ChatRole.SYSTEM
    assert messages[0].content == AEGIS_RAG_SYSTEM_PROMPT.text


def test_system_prompt_establishes_untrusted_context_rules() -> None:
    builder = RAGPromptBuilder()

    messages = builder.build(context_text="x", question="y", history=[])

    system_text = messages[0].content.lower()
    assert "untrusted" in system_text
    assert "never follow" in system_text or "not instructions" in system_text
    assert "cite" in system_text or "citation" in system_text or "[s1]" in system_text


def test_history_is_preserved_in_order_between_system_and_final_turn() -> None:
    builder = RAGPromptBuilder()
    history = [
        make_message(MessageRole.USER, "earlier question"),
        make_message(MessageRole.ASSISTANT, "earlier answer"),
    ]

    messages = builder.build(context_text="ctx", question="new question", history=history)

    assert messages[1].role == ChatRole.USER
    assert messages[1].content == "earlier question"
    assert messages[2].role == ChatRole.ASSISTANT
    assert messages[2].content == "earlier answer"


def test_final_message_combines_context_and_question() -> None:
    builder = RAGPromptBuilder()

    messages = builder.build(
        context_text="[SOURCE 1]\nDocument: a.pdf\n\nSome evidence.",
        question="What does the policy say?",
        history=[],
    )

    final = messages[-1]
    assert final.role == ChatRole.USER
    assert "CONTEXT:" in final.content
    assert "[SOURCE 1]" in final.content
    assert "Some evidence." in final.content
    assert "QUESTION:" in final.content
    assert "What does the policy say?" in final.content


def test_no_history_produces_exactly_system_and_final_turn() -> None:
    builder = RAGPromptBuilder()

    messages = builder.build(context_text="ctx", question="q", history=[])

    assert len(messages) == 2
