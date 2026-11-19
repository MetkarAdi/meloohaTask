"""Allow an unknown cost estimate for a custom Groq model."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261115_0003"
down_revision: str | None = "20261115_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("questions") as batch_op:
        batch_op.alter_column(
            "cost_usd",
            existing_type=sa.Numeric(precision=12, scale=8),
            nullable=True,
        )


def downgrade() -> None:
    op.execute("UPDATE questions SET cost_usd = 0 WHERE cost_usd IS NULL")
    with op.batch_alter_table("questions") as batch_op:
        batch_op.alter_column(
            "cost_usd",
            existing_type=sa.Numeric(precision=12, scale=8),
            nullable=False,
        )
