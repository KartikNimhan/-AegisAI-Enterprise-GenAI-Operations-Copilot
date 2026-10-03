"""Conversation retrieval/management orchestration.

Thin on purpose: conversations (listing, detail, deletion) don't need
anything beyond the repository today. Kept as its own service — rather
than folding into `ChatService` — because it has no LLM/prompt concerns at
all, and because `api/v1/conversations.py` should not depend on
`ChatService` just to read data.
"""

from __future__ import annotations

import uuid

from app.db.repositories.conversation_repository import ConversationRepository
from app.dependencies import DBSessionDep
from app.domain.models.conversation import Conversation


class ConversationService:
    def __init__(self, conversations: ConversationRepository) -> None:
        self._conversations = conversations

    async def list_conversations(self, *, limit: int = 50) -> list[Conversation]:
        return await self._conversations.list(limit=limit)

    async def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return await self._conversations.get_with_messages(conversation_id)

    async def delete_conversation(self, conversation_id: uuid.UUID) -> bool:
        return await self._conversations.delete(conversation_id)


def get_conversation_service(session: DBSessionDep) -> ConversationService:
    return ConversationService(ConversationRepository(session))
