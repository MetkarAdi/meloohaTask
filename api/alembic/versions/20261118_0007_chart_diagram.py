"""Store chart layout preference and question highlight houses."""
from typing import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20261118_0007"
down_revision: str | None = "20261118_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column("birth_profiles", sa.Column("chart_style", sa.String(16), nullable=False, server_default="north"))
    op.add_column("questions", sa.Column("highlighted_houses", sa.JSON(), nullable=False, server_default="[]"))

def downgrade() -> None:
    op.drop_column("questions", "highlighted_houses")
    op.drop_column("birth_profiles", "chart_style")
