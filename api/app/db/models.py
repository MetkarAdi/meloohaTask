from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    wallet: Mapped[Wallet] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    birth_profiles: Mapped[list[BirthProfile]] = relationship(back_populates="user", cascade="all, delete-orphan")
    questions: Mapped[list[Question]] = relationship(back_populates="user", cascade="all, delete-orphan")


class BirthProfile(Base):
    __tablename__ = "birth_profiles"
    __table_args__ = (UniqueConstraint("user_id", "cache_key", name="uq_birth_profiles_user_cache_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="My birth chart")
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    birth_time: Mapped[time] = mapped_column(Time, nullable=False)
    birth_time_unknown: Mapped[bool] = mapped_column(default=False, nullable=False)
    chart_style: Mapped[str] = mapped_column(String(16), nullable=False, default="north")
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="Asia/Kolkata")
    location: Mapped[str] = mapped_column(String(300), nullable=False)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    chart_facts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    chart_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="birth_profiles")
    questions: Mapped[list[Question]] = relationship(back_populates="birth_profile")


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_wallets_balance_nonnegative"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship(back_populates="wallet")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    birth_profile_id: Mapped[int | None] = mapped_column(ForeignKey("birth_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="answered")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    facts_used: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    highlighted_houses: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    llm_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    api_key_slot: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    user: Mapped[User] = relationship(back_populates="questions")
    birth_profile: Mapped[BirthProfile | None] = relationship(back_populates="questions")
    ledger_entry: Mapped[WalletLedger | None] = relationship(back_populates="question", uselist=False)


class WalletLedger(Base):
    __tablename__ = "wallet_ledger"
    __table_args__ = (
        CheckConstraint("amount != 0", name="ck_wallet_ledger_nonzero_amount"),
        CheckConstraint("balance_after >= 0", name="ck_wallet_ledger_balance_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"), nullable=True, unique=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    question: Mapped[Question | None] = relationship(back_populates="ledger_entry")


class AppEvent(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_user_event_timestamp", "user_id", "event", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class InsightJob(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "job_type", "run_date", name="uq_jobs_user_type_date"),
        Index("ix_jobs_status_next_attempt", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class DailyInsight(Base):
    __tablename__ = "daily_insights"
    __table_args__ = (UniqueConstraint("user_id", "run_date", name="uq_daily_insights_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    facts_used: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    llm_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
