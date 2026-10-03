"""add chunk embeddings

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(384), nullable=False),
        sa.Column("embedding_provider", sa.String(length=50), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_model_version", sa.String(length=50), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_chunk_id",
            "embedding_model",
            "embedding_model_version",
            name="uq_chunk_embeddings_chunk_model_version",
        ),
    )
    op.create_index(
        op.f("ix_chunk_embeddings_document_chunk_id"),
        "chunk_embeddings",
        ["document_chunk_id"],
        unique=False,
    )
    op.create_index(
        "ix_chunk_embeddings_model_version",
        "chunk_embeddings",
        ["embedding_model", "embedding_model_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_embeddings_model_version", table_name="chunk_embeddings")
    op.drop_index(op.f("ix_chunk_embeddings_document_chunk_id"), table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
