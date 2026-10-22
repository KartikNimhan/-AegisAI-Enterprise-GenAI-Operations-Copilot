"""add agent memories

Additive only: creates one new table, `agent_memories`, and its constraints and index. It
touches no existing table or row.

Each memory is a short note the agent keeps about ONE user across conversations. It is owned by
that user and nobody else can read it (see ADR 015): the composite foreign key
(owner_user_id, organization_id) -> users(id, organization_id) makes the database itself
guarantee that the owner belongs to the row's organization, as for `conversations` and
`documents`, and is ON DELETE RESTRICT like them. `(owner_user_id, content_hash)` is unique so
saving the same note twice refreshes it instead of duplicating it; `expires_at` is required, so
every note has a lifetime.

Downgrade drops the table and with it every stored memory (conversations, messages and documents
are untouched).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "fact",
                "preference",
                name="ck_agent_memories_kind",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "agent",
                "user",
                name="ck_agent_memories_source",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(content) BETWEEN 1 AND 2000", name="ck_agent_memories_content_length"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_agent_memories_owner_in_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "content_hash", name="uq_agent_memories_owner_hash"),
    )
    op.create_index(
        "ix_agent_memories_owner_user_id_updated_at",
        "agent_memories",
        ["owner_user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_memories_owner_user_id_updated_at", table_name="agent_memories")
    op.drop_table("agent_memories")
