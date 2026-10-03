"""Assembles the message list sent to the LLM gateway.

Structure: [system message, ...conversation history, current user message].
Kept out of `ChatService` so prompt construction can evolve independently
of orchestration (different system prompts, versioning, eventually
RAG/agent prompts) without touching the service.
"""

from __future__ import annotations

from app.domain.models.message import Message
from app.llm.schemas import ChatMessage, ChatRole
from app.prompts.schemas import PromptTemplate
from app.prompts.templates import AEGIS_CHAT_SYSTEM_PROMPT


class PromptBuilder:
    def __init__(self, system_prompt: PromptTemplate = AEGIS_CHAT_SYSTEM_PROMPT) -> None:
        self._system_prompt = system_prompt

    def build(self, *, history: list[Message], user_message: str) -> list[ChatMessage]:
        messages = [ChatMessage(role=ChatRole.SYSTEM, content=self._system_prompt.text)]
        messages.extend(
            ChatMessage(role=ChatRole(persisted.role.value), content=persisted.content)
            for persisted in history
        )
        messages.append(ChatMessage(role=ChatRole.USER, content=user_message))
        return messages
