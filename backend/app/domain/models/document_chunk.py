"""DocumentChunk persistence model.

`id` is NOT a random UUID4 — it's deterministically derived from the parent
document's checksum, the chunking configuration, and the chunk index (see
`app.documents.chunk_ids.compute_chunk_id`). No embedding/vector column
exists yet; that's the next milestone.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.domain.models.document import Document


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_index"),
        Index("ix_document_chunks_document_id_chunk_index", "document_id", "chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Left unset in this milestone — see docs/architecture/decisions/
    # 005-document-ingestion.md ("token_count"): no tokenizer dependency is
    # added until an embedding model (with a known tokenizer) is chosen.
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # e.g. {"page_numbers": [3, 4]} for a PDF chunk spanning two pages.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship("Document", back_populates="chunks")
