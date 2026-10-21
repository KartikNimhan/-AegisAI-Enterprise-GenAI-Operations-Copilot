"""Persistence for `Conversation` entities.

A conversation is private to its owner: every query applies the caller's
`AccessScope`, and a conversation that is not theirs is "not found".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.scope import AccessScope
from app.domain.models.conversation import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession, scope: AccessScope) -> None:
        self._session = session
        self._scope = scope

    async def create(
        self,
        *,
        title: str | None = None,
        owner_user_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> Conversation:
        """The owner comes from the scope; only an unrestricted (operator) scope may
        name it explicitly."""
        if self._scope.unrestricted:
            owner, organization = owner_user_id, organization_id
        else:
            if owner_user_id is not None or organization_id is not None:
                raise ValueError("owner_user_id / organization_id come from the access scope")
            if self._scope.user_id is None or self._scope.organization_id is None:
                raise ValueError("a conversation needs an owner")
            owner, organization = self._scope.user_id, self._scope.organization_id
        conversation = Conversation(title=title, owner_user_id=owner, organization_id=organization)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, self._scope.conversation_filter(Conversation)
            )
        )
        return result.scalar_one_or_none()

    async def get_with_messages(self, conversation_id: uuid.UUID) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(
                Conversation.id == conversation_id, self._scope.conversation_filter(Conversation)
            )
        )
        return result.scalar_one_or_none()

    async def list(self, *, limit: int = 50) -> list[Conversation]:
        # Tiebreak on id: two updates can land in the same timestamp tick
        # (seen in practice on fast hardware), which would otherwise make
        # pagination/ordering non-deterministic for same-instant rows.
        result = await self._session.execute(
            select(Conversation)
            .where(self._scope.conversation_filter(Conversation))
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, conversation_id: uuid.UUID) -> bool:
        conversation = await self.get(conversation_id)
        if conversation is None:
            return False
        await self._session.delete(conversation)
        await self._session.flush()
        return True

    async def touch(self, conversation: Conversation) -> None:
        """Bumps `updated_at`. Called after a new message is added."""
        conversation.updated_at = datetime.now(UTC)
