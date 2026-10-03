"""Message persistence model.

Stores one row per user or assistant turn. System prompts are built fresh
per request by `app.prompts.builder.PromptBuilder` and are intentionally
not persisted (they're static per prompt version, not per-conversation
data — see docs/architecture/decisions/004-conversation-persistence.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums.message_role import MessageRole

if TYPE_CHECKING:
    from app.domain.models.conversation import Conversation


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        # native_enum=False: a VARCHAR + CHECK constraint, not a Postgres
        # native ENUM type — far simpler to extend with a new role later
        # (ALTER TYPE ... ADD VALUE has sharp edges inside transactions).
        # create_constraint=True: SQLAlchemy 2.0 defaults this to False, so
        # without it native_enum=False silently gives up DB-level
        # enforcement entirely (plain VARCHAR, no CHECK constraint).
        # values_callable: store/compare MessageRole's *values* ("user"),
        # not its member *names* ("USER") — SQLAlchemy's Enum type uses
        # .name by default, which would silently diverge from ChatRole's
        # identical-looking string values.
        Enum(
            MessageRole,
            name="ck_messages_role",
            native_enum=False,
            length=20,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Populated for assistant messages only; null for user messages.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")
