"""Persist onboarding details and answer ratings."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261116_0005"
down_revision: str | None = "20261115_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("birth_profiles", sa.Column("display_name", sa.String(length=120), nullable=True))
    op.add_column(
        "birth_profiles",
        sa.Column("birth_time_unknown", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("questions", sa.Column("rating", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "rating")
    op.drop_column("birth_profiles", "birth_time_unknown")
    op.drop_column("birth_profiles", "display_name")
