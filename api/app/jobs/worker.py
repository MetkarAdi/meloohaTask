from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, time as daytime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.chart.calculator import calculate_chart
from app.chart.models import ChartRequest
from app.db.models import BirthProfile, DailyInsight, InsightJob, User
from app.db.session import get_session_factory
from app.llm import generate_answer
from app.llm.routing import route_question

LOGGER = logging.getLogger("melooha.jobs.daily_insight")
JOB_TYPE = "daily_insight"
LEASE_SECONDS = 300
POLL_SECONDS = 5
INSIGHT_QUESTION = "In 2 or 3 short, beginner-friendly sentences, what can today's Jupiter and Saturn transits suggest for my chart?"


def local_today(profile: BirthProfile, now: datetime | None = None) -> date:
    zone = ZoneInfo(profile.timezone or "Asia/Kolkata")
    return (now or datetime.now(timezone.utc)).astimezone(zone).date()


def enqueue_job(session: Session, user_id: int, run_date: date, job_type: str = JOB_TYPE) -> tuple[InsightJob, bool]:
    existing = session.scalar(select(InsightJob).where(
        InsightJob.user_id == user_id,
        InsightJob.job_type == job_type,
        InsightJob.run_date == run_date,
    ))
    if existing:
        return existing, False
    job = InsightJob(user_id=user_id, job_type=job_type, run_date=run_date, status="pending", attempts=0)
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
        return job, True
    except IntegrityError:
        existing = session.scalar(select(InsightJob).where(
            InsightJob.user_id == user_id,
            InsightJob.job_type == job_type,
            InsightJob.run_date == run_date,
        ))
        if existing is None:
            raise
        return existing, False


def enqueue_all_for_today(now: datetime | None = None) -> int:
    inserted = 0
    with get_session_factory()() as session:
        profiles = session.scalars(select(BirthProfile).order_by(BirthProfile.user_id, BirthProfile.updated_at.desc())).all()
        latest: dict[int, BirthProfile] = {}
        for profile in profiles:
            latest.setdefault(profile.user_id, profile)
        users = session.scalars(select(User)).all()
        session.commit()
        with session.begin():
            for user in users:
                profile = latest.get(user.id)
                run_date = local_today(profile, now) if profile else (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Kolkata")).date()
                _, created = enqueue_job(session, user.id, run_date)
                inserted += int(created)
    return inserted


def _claim_job(job_id: int | None = None, *, now: datetime | None = None, force: bool = False) -> tuple[int, int, date, int] | None:
    now = now or datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=LEASE_SECONDS)
    with get_session_factory()() as session:
        with session.begin():
            query = select(InsightJob).where(InsightJob.job_type == JOB_TYPE)
            if job_id is not None:
                query = query.where(InsightJob.id == job_id)
            ready = or_(
                InsightJob.status == "pending",
                (InsightJob.status == "failed") & ((InsightJob.next_attempt_at <= now) | force),
                (InsightJob.status == "running") & (InsightJob.claimed_at < stale_before),
            )
            job = session.scalar(query.where(ready).order_by(InsightJob.run_date, InsightJob.id).with_for_update(skip_locked=True).limit(1))
            if job is None:
                return None
            job.status = "running"
            job.attempts += 1
            job.claimed_at = now
            job.updated_at = now
            session.flush()
            result = (job.id, job.user_id, job.run_date, job.attempts)
        return result


def _profile_for_user(session: Session, user_id: int) -> BirthProfile | None:
    return session.scalar(select(BirthProfile).where(BirthProfile.user_id == user_id)
                          .order_by(BirthProfile.updated_at.desc(), BirthProfile.id.desc()).limit(1))


def _generate(user_id: int, run_date: date) -> tuple[str, list[str], str, str]:
    with get_session_factory()() as session:
        profile = _profile_for_user(session, user_id)
        if profile is None:
            raise ValueError("Birth profile is not available")
        request = ChartRequest(
            birth_date=profile.birth_date,
            birth_time=profile.birth_time,
            timezone=profile.timezone,
            location=profile.location,
            latitude=profile.latitude,
            longitude=profile.longitude,
        )
        unknown_time = profile.birth_time_unknown
        profile_timezone = profile.timezone

    noon_local = datetime.combine(run_date, daytime(hour=12), tzinfo=ZoneInfo(profile_timezone))
    chart = calculate_chart(request, as_of=noon_local)
    chart_facts = list(chart.facts)
    if unknown_time:
        chart_facts.append(f"F{len(chart_facts) + 1:03d} : Birth time was marked unknown; time-dependent placements are approximate")
    facts = route_question(INSIGHT_QUESTION, chart_facts)
    result = generate_answer(INSIGHT_QUESTION, facts, stream=False)
    if not result.succeeded or not result.answer.strip():
        raise RuntimeError("No checked insight answer was produced")
    return result.answer, facts, result.provider, result.model


def process_job(job_id: int | None = None, *, force: bool = False,
                persist_hook: Callable[[Session, DailyInsight], None] | None = None) -> dict | None:
    claim = _claim_job(job_id, force=force)
    if claim is None:
        if job_id is None:
            return None
        return get_insight_for_job(job_id)
    claimed_id, user_id, run_date, attempts = claim
    try:
        answer, facts, provider, model = _generate(user_id, run_date)
        with get_session_factory()() as session:
            with session.begin():
                job = session.scalar(select(InsightJob).where(InsightJob.id == claimed_id).with_for_update())
                existing = session.scalar(select(DailyInsight).where(
                    DailyInsight.user_id == user_id, DailyInsight.run_date == run_date,
                ))
                if existing is None:
                    existing = DailyInsight(
                        user_id=user_id, run_date=run_date, answer_text=answer,
                        facts_used=facts, llm_provider=provider, llm_model=model,
                    )
                    session.add(existing)
                    session.flush()
                    if persist_hook:
                        persist_hook(session, existing)
                if job:
                    job.status = "completed"
                    job.last_error = None
                    job.updated_at = datetime.now(timezone.utc)
                session.flush()
                result = _insight_payload(existing)
            return result
    except Exception as error:
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=min(30 * (2 ** max(attempts - 1, 0)), 3600))
        with get_session_factory()() as session:
            with session.begin():
                job = session.get(InsightJob, claimed_id)
                if job and job.status != "completed":
                    job.status = "failed"
                    job.last_error = type(error).__name__
                    job.next_attempt_at = retry_at
                    job.updated_at = datetime.now(timezone.utc)
        LOGGER.warning("Daily insight failed job_id=%s attempt=%s error=%s retry_at=%s", claimed_id, attempts, type(error).__name__, retry_at.isoformat())
        return None


def _insight_payload(insight: DailyInsight) -> dict:
    return {"id": insight.id, "run_date": insight.run_date.isoformat(), "answer_text": insight.answer_text,
            "facts_used": insight.facts_used, "llm_provider": insight.llm_provider, "llm_model": insight.llm_model}


def get_insight_for_job(job_id: int) -> dict | None:
    with get_session_factory()() as session:
        job = session.get(InsightJob, job_id)
        if job is None:
            return None
        insight = session.scalar(select(DailyInsight).where(
            DailyInsight.user_id == job.user_id, DailyInsight.run_date == job.run_date,
        ))
        return _insight_payload(insight) if insight else None


def get_or_create_today(user_id: int) -> dict | None:
    with get_session_factory()() as session:
        profile = _profile_for_user(session, user_id)
        if profile is None:
            return None
        run_date = local_today(profile)
        session.commit()
        with session.begin():
            insight = session.scalar(select(DailyInsight).where(
                DailyInsight.user_id == user_id, DailyInsight.run_date == run_date,
            ))
            if insight:
                return _insight_payload(insight)
            job, _ = enqueue_job(session, user_id, run_date)
            job_id = job.id

    result = process_job(job_id, force=True)
    if result:
        return result
    # Another worker may hold the lease. Wait briefly for its atomic commit.
    for _ in range(240):
        time.sleep(0.5)
        with get_session_factory()() as session:
            insight = session.scalar(select(DailyInsight).where(
                DailyInsight.user_id == user_id, DailyInsight.run_date == run_date,
            ))
            if insight:
                return _insight_payload(insight)
            job = session.get(InsightJob, job_id)
            if job is None or job.status == "failed":
                return None
            is_running = job.status == "running"
        if not is_running:
            result = process_job(job_id, force=True)
            if result:
                return result
    return None


def _is_jobs_table_missing(error: BaseException) -> bool:
    """Recognize PostgreSQL and SQLite missing-table errors without logging driver payloads."""
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code == "42P01":
            return True
        message = str(current).casefold()
        if ("jobs" in message and (
            "does not exist" in message or "undefined table" in message or "no such table" in message
        )):
            return True
        for nested in (getattr(current, "orig", None), current.__cause__, current.__context__):
            if isinstance(nested, BaseException):
                pending.append(nested)
        for arg in getattr(current, "args", ()):
            if isinstance(arg, dict) and arg.get("C") == "42P01":
                return True
    return False


def run_worker() -> None:
    LOGGER.info("Daily insight worker started")
    waiting_for_migrations = False
    while True:
        try:
            result = process_job()
            if waiting_for_migrations:
                LOGGER.info("Daily insight worker resumed after migrations")
                waiting_for_migrations = False
            if result is None:
                time.sleep(POLL_SECONDS)
        except Exception as error:
            if _is_jobs_table_missing(error):
                if not waiting_for_migrations:
                    LOGGER.warning("Daily insight worker waiting for migrations (jobs table is not available yet)")
                    waiting_for_migrations = True
            else:
                LOGGER.exception("Daily insight worker loop failed")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    from dotenv import load_dotenv

    api_dir = Path(__file__).resolve().parents[2]
    project_root = api_dir.parent
    load_dotenv(project_root / ".env.local")
    load_dotenv(project_root / ".env")
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    run_worker()
