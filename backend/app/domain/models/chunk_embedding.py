"""ChunkEmbedding persistence model.

One row per (chunk, embedding model, embedding model version) — not one row
per chunk. This is what lets a chunk have embeddings from multiple models
at once (for migration) while still letting a lookup by
(chunk, model, version) tell you whether that exact combination already
has a vector (idempotency). See
docs/architecture/decisions/006-embedding-model.md.

The vector column's dimension is fixed at the schema level (pgvector
requires a fixed dimension per column) to the currently selected model's
dimension. A future embedding model with a *different* dimension would
need a new column or table — see the ADR for why that's an acceptable,
documented limitation rather than something this migration tries to solve
generically.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.domain.models.document_chunk import DocumentChunk

# Must match Settings.embedding_dimension for the currently configured
# model (sentence-transformers/all-MiniLM-L6-v2 -> 384). This is a schema
# constant, not read from Settings, because changing it requires a
# migration regardless of what a config file says at runtime.
EMBEDDING_DIMENSION = 384


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        # The idempotency key: re-embedding a chunk with the same
        # model+version must not create a second row. Enforced at the DB
        # level (not just in application logic) as the final safety net.
        UniqueConstraint(
            "document_chunk_id",
            "embedding_model",
            "embedding_model_version",
            name="uq_chunk_embeddings_chunk_model_version",
        ),
        Index(
            "ix_chunk_embeddings_model_version",
            "embedding_model",
            "embedding_model_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION), nullable=False)

    # Preserved per-row, not inferred from current Settings — changing the
    # embedding model changes the vector space, so every vector must stay
    # attributable to exactly the model/version that produced it (ADR 006).
    embedding_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    document_chunk: Mapped[DocumentChunk] = relationship(
        "DocumentChunk", back_populates="embeddings"
    )
