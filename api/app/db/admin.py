from __future__ import annotations

import hmac
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppEvent, BirthProfile, User
from app.db.session import get_db, get_session_factory
from app.jobs.worker import enqueue_job, local_today

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(admin_secret: str | None = Header(default=None, alias="ADMIN_SECRET")) -> None:
    configured = os.getenv("ADMIN_SECRET", "").strip()
    if not configured or not admin_secret or not hmac.compare_digest(configured, admin_secret):
        raise HTTPException(status_code=403, detail="Admin access is not available.")


@router.post("/schedule-insights", dependencies=[Depends(require_admin)])
def schedule_insights():
    inserted = 0
    eligible_users = 0
    with get_session_factory()() as session:
        profiles = session.scalars(select(BirthProfile).order_by(BirthProfile.user_id, BirthProfile.updated_at.desc())).all()
        latest: dict[int, BirthProfile] = {}
        for profile in profiles:
            latest.setdefault(profile.user_id, profile)
        users = session.scalars(select(User)).all()
        session.commit()
        with session.begin():
            for user in users:
                eligible_users += 1
                profile = latest.get(user.id)
                run_date = local_today(profile) if profile else datetime.now(ZoneInfo("Asia/Kolkata")).date()
                _, created = enqueue_job(session, user.id, run_date)
                inserted += int(created)
    return {"eligible_users": eligible_users, "jobs_added": inserted}


def _rate(numerator: int, denominator: int) -> dict:
    return {"rate": round(numerator / denominator, 4) if denominator else 0.0,
            "users": numerator, "eligible_users": denominator}


@router.get("/metrics", dependencies=[Depends(require_admin)])
def metrics(session: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    users_total = session.query(User.id).count()
    rows = session.execute(select(AppEvent.user_id, AppEvent.event, AppEvent.timestamp).where(
        AppEvent.event.in_({"signup", "session_start", "insight_viewed", "facts_sheet_opened"}),
    )).all()
    signups: dict[int, date] = {}
    sessions_by_user: dict[int, set[date]] = defaultdict(set)
    insight_viewers: set[int] = set()
    facts_openers: set[int] = set()
    for user_id, event, timestamp in rows:
        event_date = timestamp.astimezone(timezone.utc).date() if timestamp.tzinfo else timestamp.date()
        if event == "signup":
            signups[user_id] = min(signups.get(user_id, event_date), event_date)
        elif event == "session_start":
            sessions_by_user[user_id].add(event_date)
        elif event == "insight_viewed":
            insight_viewers.add(user_id)
        elif event == "facts_sheet_opened":
            facts_openers.add(user_id)

    retained = {1: (0, 0), 7: (0, 0)}
    for user_id, signup_date in signups.items():
        age_days = (today - signup_date).days
        for day in (1, 7):
            if age_days >= day:
                eligible, returned = retained[day]
                retained[day] = (eligible + 1, returned + int(signup_date + timedelta(days=day) in sessions_by_user[user_id]))

    return {
        "as_of": today.isoformat(),
        "users_total": users_total,
        "day_1_return_rate": _rate(retained[1][1], retained[1][0]),
        "day_7_return_rate": _rate(retained[7][1], retained[7][0]),
        "share_viewed_insight": _rate(len(insight_viewers), users_total),
        "share_opened_facts_sheet": _rate(len(facts_openers), users_total),
    }
