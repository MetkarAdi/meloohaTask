from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppEvent, BirthProfile, User
from app.db.session import get_db
from app.jobs.worker import get_or_create_today
from .auth import get_current_user

router = APIRouter(tags=["insights"])


class EventRequest(BaseModel):
    event: Literal["session_start", "insight_viewed", "facts_sheet_opened", "home_viewed", "chart_image_shared"]


@router.post("/events", status_code=201)
def log_event(body: EventRequest, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    row = AppEvent(user_id=user.id, event=body.event)
    session.add(row)
    session.commit()
    return {"event": row.event, "timestamp": row.timestamp}


def current_streak(session: Session, user_id: int, today: date | None = None, timezone_name: str = "UTC") -> int:
    today = today or datetime.now(timezone.utc).date()
    zone = ZoneInfo(timezone_name)
    rows = session.scalars(select(AppEvent.timestamp).where(
        AppEvent.user_id == user_id, AppEvent.event == "session_start",
    )).all()
    days = {(value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(zone).date() for value in rows}
    streak = 0
    check = today
    while check in days:
        streak += 1
        check -= timedelta(days=1)
    return streak


@router.get("/insight/today")
def today_insight(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    result = get_or_create_today(user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="Add birth details to create today's insight.")
    run_date = date.fromisoformat(result["run_date"])
    profile = session.scalar(select(BirthProfile).where(BirthProfile.user_id == user.id)
                             .order_by(BirthProfile.updated_at.desc(), BirthProfile.id.desc()).limit(1))
    zone = profile.timezone if profile else "UTC"
    return {**result, "streak_days": current_streak(session, user.id, today=run_date, timezone_name=zone), "run_date": run_date.isoformat()}
