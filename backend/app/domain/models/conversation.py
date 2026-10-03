"""Conversation persistence model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.domain.models.message import Message


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # default= (Python-side, evaluated by the ORM) takes precedence over
    # server_default for ORM-driven inserts; server_default remains only as
    # a DB-level fallback for any non-ORM insert. This keeps created_at on
    # the same clock as ConversationRepository.touch()'s explicit
    # updated_at assignment below — mixing the app server's clock with
    # Postgres's own clock caused touch()-ed rows to occasionally sort
    # *before* newly created ones under a few milliseconds of clock skew
    # between the two processes (reproduced in Docker Desktop on Windows).
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

    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
        # The FK is declared with ondelete="CASCADE"; let Postgres handle
        # cascading deletes rather than SQLAlchemy loading every child row.
        passive_deletes=True,
    )
