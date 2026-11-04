"""add message citations

Additive only: creates one new table, `message_citations`, with its constraints. It touches no
existing table or row, and backfills nothing: messages saved before this migration simply have
no citation rows (M10.4 decision 7).

Each row is a REFERENCE to one source an assistant message's answer was grounded in (`S1`,
`S2`, ...), never document text (M10.4 decision 2):
- `message_id` -> messages(id) ON DELETE CASCADE: deleting a message (and so a conversation)
  deletes its citations.
- `document_id` and `chunk_id` deliberately have NO foreign key: a reference survives the
  document's deletion and reads as unavailable (decision 2; kept subject to the M9.5 retention
  policy, decision 10).
- `rendering_version` and `passage_sha256` let a read verify that the passage rebuilt from the
  stored chunk is exactly the one the model saw (decision 4).
- `UNIQUE (message_id, source_id)`: one row per source id per message. `source_id` must equal
  'S' || position, so this also makes (message_id, position) unique; no second constraint.
- `similarity` is constrained to [-1.0, 1.0]; the writer clamps finite values into that range
  and rejects non-finite ones (owner decision, 2026-11-03).

Downgrade drops the table and with it every saved citation reference (conversations, messages
and documents are untouched).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(length=16), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("similarity", sa.Double(), nullable=False),
        sa.Column("cited", sa.Boolean(), nullable=False),
        sa.Column("passage_chars", sa.Integer(), nullable=False),
        sa.Column("passage_truncated", sa.Boolean(), nullable=False),
        sa.Column("rendering_version", sa.String(length=32), nullable=False),
        sa.Column("passage_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_citations"),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_message_citations_message_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("message_id", "source_id", name="uq_message_citations_message_source"),
        sa.CheckConstraint(
            "source_id ~ '^S[1-9][0-9]{0,2}$'", name="ck_message_citations_source_id_format"
        ),
        sa.CheckConstraint(
            """source_id = 'S' || "position"::text""",
            name="ck_message_citations_source_id_position",
        ),
        sa.CheckConstraint('"position" > 0', name="ck_message_citations_position_positive"),
        sa.CheckConstraint("passage_chars >= 0", name="ck_message_citations_passage_chars"),
        sa.CheckConstraint(
            "passage_sha256 ~ '^[0-9a-f]{64}$'", name="ck_message_citations_passage_sha256"
        ),
        sa.CheckConstraint(
            "char_length(rendering_version) > 0", name="ck_message_citations_rendering_version"
        ),
        sa.CheckConstraint(
            "similarity BETWEEN -1.0 AND 1.0", name="ck_message_citations_similarity"
        ),
    )


def downgrade() -> None:
    op.drop_table("message_citations")
