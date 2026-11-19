"""Persist structured answer sections for multi-bubble chat responses."""

from alembic import op
import sqlalchemy as sa

revision = "20261119_0008"
down_revision = "20261118_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("answer_sections", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "answer_sections")
