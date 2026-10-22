"""Assembles the message list sent to the LLM gateway for a RAG turn.

Mirrors `app.prompts.builder.PromptBuilder`'s shape
([system, ...history, new message]) but with the RAG system prompt and a
final user turn that wraps the assembled context and the question together
— this is the one place CONTEXT and QUESTION are combined into prompt
text, kept out of `RAGService` per the project's "no prompt string
construction in services" rule.
"""

from __future__ import annotations

from app.domain.models.message import Message
from app.llm.schemas import ChatMessage, ChatRole
from app.prompts.history import HistoryLimits, select_recent_history
from app.prompts.schemas import PromptTemplate
from app.rag.prompts.templates import AEGIS_RAG_SYSTEM_PROMPT


class RAGPromptBuilder:
    def __init__(
        self,
        system_prompt: PromptTemplate = AEGIS_RAG_SYSTEM_PROMPT,
        history_limits: HistoryLimits | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._history_limits = history_limits or HistoryLimits()

    def build(
        self, *, context_text: str, question: str, history: list[Message]
    ) -> list[ChatMessage]:
        messages = [ChatMessage(role=ChatRole.SYSTEM, content=self._system_prompt.text)]
        messages.extend(
            ChatMessage(role=ChatRole(persisted.role.value), content=persisted.content)
            for persisted in select_recent_history(history, self._history_limits)
        )
        messages.append(
            ChatMessage(
                role=ChatRole.USER,
                content=f"CONTEXT:\n{context_text}\n\nQUESTION:\n{question}",
            )
        )
        return messages
