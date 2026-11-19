"""Seed deterministic demo events into the configured database.

Run from api/: python -m scripts.seed_demo --count 30
This script uses the process DATABASE_URL; use a demo database, never production.
"""

import argparse
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db.auth import hash_password
from app.db.models import AppEvent, User
from app.db.session import get_session_factory


def seed(count: int) -> tuple[int, int]:
    today = datetime.now(timezone.utc).date()
    users_added = 0
    events_added = 0
    with get_session_factory()() as session, session.begin():
        for index in range(count):
            email = f"demo.user.{index + 1:03d}@example.test"
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, password_hash=hash_password("demo-password-not-for-real-use"))
                session.add(user)
                session.flush()
                users_added += 1

            signup_day = today - timedelta(days=8 + (index % 6))
            timeline = [("signup", signup_day)]
            if index % 5 != 0:
                timeline.append(("session_start", signup_day + timedelta(days=1)))
            if index % 3 == 0:
                timeline.append(("session_start", signup_day + timedelta(days=7)))
            if index % 4 != 0:
                timeline.append(("session_start", today))
            if index % 2 == 0:
                timeline.append(("insight_viewed", today))
            if index % 3 == 0:
                timeline.append(("facts_sheet_opened", today))
            if index % 4 == 0:
                timeline.append(("first_question", signup_day))

            for event_name, event_day in timeline:
                timestamp = datetime.combine(event_day, time(hour=12), tzinfo=timezone.utc)
                before = session.scalar(select(AppEvent.id).where(
                    AppEvent.user_id == user.id,
                    AppEvent.event == event_name,
                    AppEvent.timestamp == timestamp,
                ).limit(1))
                if before is None:
                    session.add(AppEvent(user_id=user.id, event=event_name, timestamp=timestamp))
                    events_added += 1
        session.flush()
    return users_added, events_added


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed fake users and engagement events for a demo.")
    parser.add_argument("--count", type=int, default=30, help="number of synthetic users (1-500; default: 30)")
    args = parser.parse_args()
    if not 1 <= args.count <= 500:
        parser.error("--count must be between 1 and 500")
    users, events = seed(args.count)
    print(f"Demo seed complete: {users} users created, {events} events added.")


if __name__ == "__main__":
    main()
