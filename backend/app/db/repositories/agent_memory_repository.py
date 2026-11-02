"""Persistence for `AgentMemory`.

Every query applies the caller's `AccessScope.memory_filter`: a memory belongs to exactly one
user, so another user's (or another organization's) memory is simply not found.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import AccessScope
from app.domain.enums.memory_kind import MemoryKind, MemorySource
from app.domain.models.agent_memory import AgentMemory
from app.domain.models.user import User


class AgentMemoryRepository:
    def __init__(self, session: AsyncSession, scope: AccessScope) -> None:
        self._session = session
        self._scope = scope

    async def create(
        self,
        *,
        content: str,
        content_hash: str,
        kind: MemoryKind,
        source: MemorySource,
        now: datetime,
        expires_at: datetime,
    ) -> AgentMemory:
        """The owner always comes from the scope; it can never be passed in."""
        if self._scope.user_id is None or self._scope.organization_id is None:
            raise ValueError("a memory needs an owner")
        memory = AgentMemory(
            owner_user_id=self._scope.user_id,
            organization_id=self._scope.organization_id,
            content=content,
            content_hash=content_hash,
            kind=kind,
            source=source,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        self._session.add(memory)
        await self._session.flush()
        return memory

    async def get(self, memory_id: uuid.UUID) -> AgentMemory | None:
        result = await self._session.execute(
            select(AgentMemory).where(
                AgentMemory.id == memory_id, self._scope.memory_filter(AgentMemory)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, content_hash: str) -> AgentMemory | None:
        result = await self._session.execute(
            select(AgentMemory).where(
                AgentMemory.content_hash == content_hash, self._scope.memory_filter(AgentMemory)
            )
        )
        return result.scalar_one_or_none()

    async def list_active(self, *, now: datetime, limit: int) -> list[AgentMemory]:
        """Unexpired memories, most recently updated first; never more than `limit`."""
        result = await self._session.execute(
            select(AgentMemory)
            .where(self._scope.memory_filter(AgentMemory), AgentMemory.expires_at > now)
            .order_by(AgentMemory.updated_at.desc(), AgentMemory.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    def lock_statement(self):
        """`SELECT ... FOR UPDATE` on the owner's user row (PostgreSQL; the clause is ignored by
        databases without row locks)."""
        return select(User.id).where(User.id == self._scope.user_id).with_for_update()

    async def lock_owner(self) -> None:
        """Serializes this user's memory writes until the transaction ends, so two concurrent
        requests cannot both pass the "is there room?" check. Without a row (or without row
        locks) it does nothing: the per-user cap is then best effort, as documented."""
        if self._scope.user_id is None:
            return
        await self._session.execute(self.lock_statement())

    async def count_active(self, *, now: datetime) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(AgentMemory)
            .where(self._scope.memory_filter(AgentMemory), AgentMemory.expires_at > now)
        )
        return int(result.scalar_one())

    async def refresh(
        self, memory: AgentMemory, *, kind: MemoryKind, now: datetime, expires_at: datetime
    ) -> AgentMemory:
        """Re-saving an existing note extends its life instead of duplicating it."""
        memory.kind = kind
        memory.expires_at = expires_at
        memory.updated_at = now  # explicit: see ConversationRepository.touch
        await self._session.flush()
        return memory

    async def update_content(
        self,
        memory: AgentMemory,
        *,
        content: str,
        content_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> AgentMemory:
        memory.content = content
        memory.content_hash = content_hash
        memory.expires_at = expires_at
        memory.updated_at = now
        await self._session.flush()
        return memory

    async def delete(self, memory_id: uuid.UUID) -> bool:
        memory = await self.get(memory_id)
        if memory is None:
            return False
        await self._session.delete(memory)
        await self._session.flush()
        return True

    async def delete_all(self) -> int:
        """Removes every memory the caller owns; returns how many."""
        result = await self._session.execute(
            delete(AgentMemory).where(self._scope.memory_filter(AgentMemory))
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def delete_expired(self, *, now: datetime) -> int:
        result = await self._session.execute(
            delete(AgentMemory).where(
                self._scope.memory_filter(AgentMemory), AgentMemory.expires_at <= now
            )
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
