"""Queries behind the one-off assignment of pre-ownership data to a user.

Deliberately NOT scoped (there is no signed-in caller): it is used only by the
operator command `scripts/assign_legacy_data.py`, and every statement is limited to
rows that have no owner yet, so it can never take a row away from its owner.
"""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.conversation import Conversation
from app.domain.models.document import Document


class LegacyOwnershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_unowned(self) -> tuple[int, int]:
        """(conversations, documents) that have no owner."""
        conversations = await self._session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.owner_user_id.is_(None))
        )
        documents = await self._session.scalar(
            select(func.count()).select_from(Document).where(Document.owner_user_id.is_(None))
        )
        return conversations or 0, documents or 0

    async def assign_unowned(
        self, *, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> tuple[int, int]:
        """Gives every unowned conversation and document to this user (documents stay
        private). Rows that already have an owner are not matched. Returns the number of
        (conversations, documents) updated."""
        conversations = cast(
            "CursorResult[tuple[()]]",
            await self._session.execute(
                update(Conversation)
                .where(Conversation.owner_user_id.is_(None))
                .values(owner_user_id=user_id, organization_id=organization_id)
            ),
        )
        documents = cast(
            "CursorResult[tuple[()]]",
            await self._session.execute(
                update(Document)
                .where(Document.owner_user_id.is_(None))
                .values(owner_user_id=user_id, organization_id=organization_id)
            ),
        )
        return conversations.rowcount, documents.rowcount
