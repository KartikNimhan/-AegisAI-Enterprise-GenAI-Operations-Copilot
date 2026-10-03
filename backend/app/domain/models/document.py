"""Document persistence model.

One row per uploaded file. `filename` is the internal storage key (safe,
generated — see `app.storage`); `original_filename` is the client-supplied
name, sanitized to a bare basename and kept for display only. Neither is
ever used to build a filesystem path outside `app.storage`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType

if TYPE_CHECKING:
    from app.domain.models.document_chunk import DocumentChunk


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(
            DocumentType,
            name="ck_documents_document_type",
            native_enum=False,
            length=20,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # SHA-256 hex digest of the raw uploaded bytes. Indexed (not unique) —
    # duplicate detection is a service-layer decision (look up, then decide
    # what to do), not a database constraint; see DocumentService.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="ck_documents_status",
            native_enum=False,
            length=20,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=DocumentStatus.UPLOADED,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Structured, small, extensible info that doesn't warrant its own
    # column (e.g. encoding used, docx paragraph count) — never raw
    # extracted text or anything unbounded in size.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    # default= (Python-side) takes precedence over server_default for
    # ORM-driven inserts, keeping created_at on the same clock as
    # DocumentService's explicit updated_at/processed_at assignments during
    # processing — mixing the app server's clock with Postgres's own caused
    # occasional, hard-to-reproduce ordering inversions under a few
    # milliseconds of clock skew between the two processes (see the
    # identical issue and fix for Conversation.created_at).
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
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk",
        back_populates="document",
        order_by="DocumentChunk.chunk_index",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
