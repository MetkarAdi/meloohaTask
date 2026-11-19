from __future__ import annotations

import os
import logging
import ssl
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

LOGGER = logging.getLogger("melooha.database")
DB_CONNECT_TIMEOUT_SECONDS = 15


def configured_database_url() -> str | None:
    return _normalize_database_url(os.getenv("DATABASE_URL", ""))


def configured_migration_database_url() -> str | None:
    # Neon pooled connections are for application queries; Alembic needs a
    # direct connection so session-level migration behavior is reliable.
    return _normalize_database_url(
        os.getenv("DATABASE_URL_UNPOOLED", "") or os.getenv("DATABASE_URL", "")
    )


def _normalize_database_url(value: str) -> str | None:
    raw_url = value.strip()
    if not raw_url:
        return None
    url = make_url(raw_url)
    if url.get_backend_name() == "postgresql":
        # pg8000 requires TLS through an SSLContext; libpq-only SSL negotiation
        # options must not be forwarded as DBAPI keyword arguments.
        url = url.set(drivername="postgresql+pg8000").difference_update_query(
            ["sslmode", "channel_binding"]
        )
    return url.render_as_string(hide_password=False)


def _connect_args(url: str) -> dict:
    if make_url(url).get_backend_name() != "postgresql":
        return {}
    return {
        "ssl_context": ssl.create_default_context(),
        "timeout": DB_CONNECT_TIMEOUT_SECONDS,
    }


@lru_cache(maxsize=4)
def _engine_for_url(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args=_connect_args(url))


def get_engine() -> Engine:
    url = configured_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return _engine_for_url(url)


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db():
    try:
        factory = get_session_factory()
    except RuntimeError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=str(exc)) from exc
    with factory() as session:
        yield session


def run_migrations() -> None:
    url = configured_migration_database_url()
    if not url:
        return
    api_dir = Path(__file__).resolve().parents[2]
    config = Config(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    LOGGER.info("Database migrations starting")
    try:
        command.upgrade(config, "head")
    except Exception:
        LOGGER.exception("Database migrations failed")
        raise
    LOGGER.info("Database migrations completed")


def verify_database_connection() -> None:
    engine = get_engine()
    LOGGER.info("Database connection starting")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        LOGGER.exception("Database connection failed")
        raise
    LOGGER.info("Database connection established")


def shutdown_database() -> None:
    _engine_for_url.cache_clear()
