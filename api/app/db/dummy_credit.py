from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

from .models import User
from .session import get_session_factory, run_migrations
from .wallet import adjust_wallet

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")


def add_dummy_questions(email: str) -> int:
    if os.getenv("APP_ENV", "development").lower() in {"prod", "production"}:
        raise RuntimeError("Dummy question credits are disabled in production.")
    run_migrations()
    factory = get_session_factory()
    with factory() as session, session.begin():
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise LookupError(f"No user found for {email!r}")
        balance = adjust_wallet(
            session,
            user_id=user.id,
            amount=10,
            reason="dummy_credit",
            note="Development test credit; no payment",
        )
        if balance is None:
            raise RuntimeError("Could not add dummy credits.")
        return balance


def main() -> None:
    parser = argparse.ArgumentParser(description="Add 10 no-payment test questions to a development user wallet.")
    parser.add_argument("email", help="email address of the development test user")
    args = parser.parse_args()
    try:
        balance = add_dummy_questions(args.email)
    except (RuntimeError, LookupError) as exc:
        parser.error(str(exc))
    print(f"Added 10 dummy questions. New balance: {balance}")


if __name__ == "__main__":
    main()
