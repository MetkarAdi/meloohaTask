"""Record the Groq API key slot used for a question."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261115_0002"
down_revision: str | None = "20261115_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("api_key_slot", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "api_key_slot")
