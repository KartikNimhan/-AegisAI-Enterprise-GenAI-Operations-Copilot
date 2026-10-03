"""Persistence for `Conversation` entities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.conversation import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, title: str | None = None) -> Conversation:
        conversation = Conversation(title=title)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        return await self._session.get(Conversation, conversation_id)

    async def get_with_messages(self, conversation_id: uuid.UUID) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def list(self, *, limit: int = 50) -> list[Conversation]:
        # Tiebreak on id: two updates can land in the same timestamp tick
        # (seen in practice on fast hardware), which would otherwise make
        # pagination/ordering non-deterministic for same-instant rows.
        result = await self._session.execute(
            select(Conversation)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, conversation_id: uuid.UUID) -> bool:
        conversation = await self._session.get(Conversation, conversation_id)
        if conversation is None:
            return False
        await self._session.delete(conversation)
        await self._session.flush()
        return True

    async def touch(self, conversation: Conversation) -> None:
        """Bumps `updated_at`. Called after a new message is added."""
        conversation.updated_at = datetime.now(UTC)
