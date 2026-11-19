"""Allow pending, failed, and out-of-balance draft questions."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261115_0004"
down_revision: str | None = "20261115_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("questions") as batch_op:
        batch_op.alter_column(
            "answer_text",
            existing_type=sa.Text(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default="answered")
        )


def downgrade() -> None:
    op.execute("UPDATE questions SET answer_text = '' WHERE answer_text IS NULL")
    with op.batch_alter_table("questions") as batch_op:
        batch_op.drop_column("status")
        batch_op.alter_column(
            "answer_text",
            existing_type=sa.Text(),
            nullable=False,
        )
