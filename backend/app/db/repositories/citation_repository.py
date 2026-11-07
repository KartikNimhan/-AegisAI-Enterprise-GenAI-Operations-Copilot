"""Persistence for `MessageCitation` rows (M10.4).

Citations have no owner of their own: they belong to an assistant message, which belongs to a
conversation, which belongs to one user. Every read and write is therefore checked against the
caller's `AccessScope` through that conversation (`conversation_filter`), exactly like
`MessageRepository`. A citation of someone else's message behaves as if it did not exist.

This repository answers "which sources did this answer use?". It never decides whether the
caller may read a cited DOCUMENT today: that is checked separately, on every read, through
`DocumentChunkRepository` and the document read filter (M10.4 decision 2).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import AccessScope
from app.core.exceptions import NotFoundError
from app.domain.enums.message_role import MessageRole
from app.domain.models.conversation import Conversation
from app.domain.models.message import Message
from app.domain.models.message_citation import MessageCitation
from app.rag.citation_records import CitationRecord


class CitationRepository:
    def __init__(self, session: AsyncSession, scope: AccessScope) -> None:
        self._session = session
        self._scope = scope

    async def add_for_message(
        self, *, message_id: uuid.UUID, records: Sequence[CitationRecord]
    ) -> None:
        """Saves the citations of an ASSISTANT message the caller may see, in the current
        transaction (the caller's commit or rollback decides whether they persist)."""
        if not records:
            return
        visible = await self._session.scalar(
            select(Message.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Message.role == MessageRole.ASSISTANT,
                self._scope.conversation_filter(Conversation),
            )
        )
        if visible is None:
            raise NotFoundError(f"Message {message_id} not found")
        self._session.add_all(
            [
                MessageCitation(
                    message_id=message_id,
                    source_id=record.source_id,
                    position=record.position,
                    document_id=record.document_id,
                    chunk_id=record.chunk_id,
                    similarity=record.similarity,
                    cited=record.cited,
                    passage_chars=record.passage_chars,
                    passage_truncated=record.passage_truncated,
                    rendering_version=record.rendering_version,
                    passage_sha256=record.passage_sha256,
                )
                for record in records
            ]
        )
        await self._session.flush()

    def _visible(self, conversation_id: uuid.UUID):
        return (
            select(MessageCitation)
            .join(Message, Message.id == MessageCitation.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.conversation_id == conversation_id,
                self._scope.conversation_filter(Conversation),
            )
        )

    async def get(
        self, *, conversation_id: uuid.UUID, message_id: uuid.UUID, source_id: str
    ) -> MessageCitation | None:
        """One citation of a message in the caller's own conversation, or None."""
        result = await self._session.execute(
            self._visible(conversation_id).where(
                MessageCitation.message_id == message_id, MessageCitation.source_id == source_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[MessageCitation]:
        """Every citation of every message in the caller's own conversation, in one query,
        ordered by message and source position."""
        result = await self._session.execute(
            self._visible(conversation_id).order_by(
                MessageCitation.message_id, MessageCitation.position
            )
        )
        return list(result.scalars().all())
