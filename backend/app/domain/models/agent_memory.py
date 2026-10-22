"""Agent memory: a short note the agent keeps about one user across conversations.

Private to its owner (see `AccessScope.memory_filter`): never shared with the organization or
with administrators. The composite foreign key makes the database itself guarantee that the
owner belongs to the row's organization, like `conversations` and `documents`. Notes expire
(`expires_at`); an expired note is not recalled and is purged on the owner's next write.
`content_hash` makes saving the same note twice a refresh instead of a duplicate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums.memory_kind import MemoryKind, MemorySource

# Database-level ceiling; the configured per-item limit (AGENT_MEMORY_MAX_ITEM_CHARS, at most 2000)
# is enforced by the service and can only be lower.
MEMORY_CONTENT_HARD_LIMIT = 2000


def _enum(enum_cls: type[MemoryKind] | type[MemorySource], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=20,
        validate_strings=True,
        create_constraint=True,
        values_callable=lambda cls: [member.value for member in cls],
    )


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_agent_memories_owner_in_organization",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_user_id", "content_hash", name="uq_agent_memories_owner_hash"),
        CheckConstraint(
            f"char_length(content) BETWEEN 1 AND {MEMORY_CONTENT_HARD_LIMIT}",
            name="ck_agent_memories_content_length",
        ),
        Index("ix_agent_memories_owner_user_id_updated_at", "owner_user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[MemoryKind] = mapped_column(
        _enum(MemoryKind, "ck_agent_memories_kind"), nullable=False, default=MemoryKind.FACT
    )
    source: Mapped[MemorySource] = mapped_column(
        _enum(MemorySource, "ck_agent_memories_source"), nullable=False, default=MemorySource.AGENT
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of the normalized, lower-cased content: dedup key (per owner).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
