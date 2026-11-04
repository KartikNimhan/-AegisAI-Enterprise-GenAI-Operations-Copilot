"""MessageCitation persistence model (M10.4 T3).

One row per source an assistant message's answer was grounded in: the `S1`, `S2`, ... ids the
model saw in its context, saved so a reopened conversation can resolve its citation markers.

What is stored is a REFERENCE, never document text (M10.4 decision 2):
- `document_id` and `chunk_id` are plain UUID columns with NO foreign key, so a reference
  survives the document's deletion and is reported as unavailable instead of disappearing
  (decision 2). Every read must recheck the caller's current access to the document.
- The exact passage the model saw is rebuilt from the stored chunk with
  `app.rag.context.assembler.model_visible_passage(content, passage_chars)`. `rendering_version`
  names the rendering used and `passage_sha256` is the SHA-256 (64 lowercase hex characters) of
  that passage's UTF-8 bytes; a read whose rebuilt passage does not match both is unavailable
  (decision 4). The hash is never returned by the API.
- `similarity` is the retrieval score, constrained to [-1.0, 1.0]. The writer (T4) must reject
  non-finite values (NaN, +/-infinity) and clamp finite ones into the range before saving
  (owner decision, 2026-11-03: floating-point rounding in pgvector could otherwise yield a value
  a hair outside it).

Ownership comes from the message (message -> conversation -> its owner), as for `Message`
itself; there are no owner columns. Deleting the message (and so its conversation) deletes its
citations through the database (`ON DELETE CASCADE`). Deliberately no ORM relationship to
`Message`: it would add ORM-side cascades and lazy loading in async code for nothing.

`source_id` and `position` describe the same thing (`S3` is position 3). The CHECK below ties
them together, so `UNIQUE (message_id, source_id)` also makes `(message_id, position)` unique.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The CHECK expressions, shared with migration 0009 by value (the migration must not import the
# model; the offline tests check the two agree).
SOURCE_ID_FORMAT_CHECK = "source_id ~ '^S[1-9][0-9]{0,2}$'"
SOURCE_ID_POSITION_CHECK = """source_id = 'S' || "position"::text"""
POSITION_CHECK = '"position" > 0'
PASSAGE_CHARS_CHECK = "passage_chars >= 0"
SHA256_CHECK = "passage_sha256 ~ '^[0-9a-f]{64}$'"
RENDERING_VERSION_CHECK = "char_length(rendering_version) > 0"
SIMILARITY_CHECK = "similarity BETWEEN -1.0 AND 1.0"


class MessageCitation(Base):
    __tablename__ = "message_citations"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_message_citations"),
        UniqueConstraint("message_id", "source_id", name="uq_message_citations_message_source"),
        CheckConstraint(SOURCE_ID_FORMAT_CHECK, name="ck_message_citations_source_id_format"),
        CheckConstraint(SOURCE_ID_POSITION_CHECK, name="ck_message_citations_source_id_position"),
        CheckConstraint(POSITION_CHECK, name="ck_message_citations_position_positive"),
        CheckConstraint(PASSAGE_CHARS_CHECK, name="ck_message_citations_passage_chars"),
        CheckConstraint(SHA256_CHECK, name="ck_message_citations_passage_sha256"),
        CheckConstraint(RENDERING_VERSION_CHECK, name="ck_message_citations_rendering_version"),
        CheckConstraint(SIMILARITY_CHECK, name="ck_message_citations_similarity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="CASCADE", name="fk_message_citations_message_id"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # References only: deliberately no foreign keys (see the module docstring).
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    chunk_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    similarity: Mapped[float] = mapped_column(Double, nullable=False)
    cited: Mapped[bool] = mapped_column(Boolean, nullable=False)
    passage_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    passage_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rendering_version: Mapped[str] = mapped_column(String(32), nullable=False)
    passage_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
