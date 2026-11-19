"""Persist daily insights, background jobs, and product events."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261118_0006"
down_revision: str | None = "20261116_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_events_user_event_timestamp", "events", ["user_id", "event", "timestamp"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "job_type", "run_date", name="uq_jobs_user_type_date"),
    )
    op.create_index("ix_jobs_status_next_attempt", "jobs", ["status", "next_attempt_at"])

    op.create_table(
        "daily_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("facts_used", sa.JSON(), nullable=False),
        sa.Column("llm_provider", sa.String(length=80), nullable=False),
        sa.Column("llm_model", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "run_date", name="uq_daily_insights_user_date"),
    )
    op.create_index("ix_daily_insights_user_id", "daily_insights", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_daily_insights_user_id", table_name="daily_insights")
    op.drop_table("daily_insights")
    op.drop_index("ix_jobs_status_next_attempt", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_events_user_event_timestamp", table_name="events")
    op.drop_table("events")
