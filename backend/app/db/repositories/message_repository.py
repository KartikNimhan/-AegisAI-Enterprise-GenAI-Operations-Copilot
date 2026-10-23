"""Persistence for `Message` entities.

Messages have no owner of their own: they belong to their conversation, so every
read and write is checked against the caller's `AccessScope` through that
conversation. A conversation that is not the caller's behaves as if it did not
exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import AccessScope
from app.core.exceptions import NotFoundError
from app.domain.enums.message_role import MessageRole
from app.domain.models.conversation import Conversation
from app.domain.models.message import Message, message_order


class MessageRepository:
    def __init__(
        self,
        session: AsyncSession,
        scope: AccessScope,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._scope = scope
        self._clock = clock
        self._last_created_at: datetime | None = None

    def _next_created_at(self) -> datetime:
        # Set here rather than by the database: its default, now(), is the start of the
        # transaction, which a turn's user message and reply share. Strictly increasing within one
        # repository (one request), so the reply always sorts after the message it answers.
        now = self._clock()
        if self._last_created_at is not None and now <= self._last_created_at:
            now = self._last_created_at + timedelta(microseconds=1)
        self._last_created_at = now
        return now

    async def _conversation_is_visible(self, conversation_id: uuid.UUID) -> bool:
        found = await self._session.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id, self._scope.conversation_filter(Conversation)
            )
        )
        return found is not None

    async def add(
        self,
        *,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        model: str | None = None,
        provider: str | None = None,
        finish_reason: str | None = None,
        request_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> Message:
        if not await self._conversation_is_visible(conversation_id):
            raise NotFoundError(f"Conversation {conversation_id} not found")
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            model=model,
            provider=provider,
            finish_reason=finish_reason,
            request_id=request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            created_at=self._next_created_at(),
        )
        self._session.add(message)
        await self._session.flush()
        return message

    def _visible_messages(self, conversation_id: uuid.UUID):
        return (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id == conversation_id,
                self._scope.conversation_filter(Conversation),
            )
        )

    async def list_by_conversation(self, conversation_id: uuid.UUID) -> list[Message]:
        result = await self._session.execute(
            self._visible_messages(conversation_id).order_by(*message_order())
        )
        return list(result.scalars().all())

    async def list_recent(self, conversation_id: uuid.UUID, *, limit: int) -> list[Message]:
        """The newest `limit` messages, oldest first. A turn only replays a bounded window of
        history (`app.prompts.history`), so it never needs to load the whole conversation."""
        result = await self._session.execute(
            self._visible_messages(conversation_id)
            .order_by(*(column.desc() for column in message_order()))
            .limit(limit)
        )
        newest_first = list(result.scalars().all())
        newest_first.reverse()
        return newest_first
