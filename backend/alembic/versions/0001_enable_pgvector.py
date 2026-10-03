"""enable pgvector extension

Revision ID: 0001
Revises:
Create Date: 2026-10-03

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Requires a Postgres image with pgvector installed (see docker-compose.yml,
    # which uses pgvector/pgvector:pg16). No tables use the `vector` type yet —
    # this only makes the extension available for the future RAG milestone.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
