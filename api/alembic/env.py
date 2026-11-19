from __future__ import annotations

import sys
import logging
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_DIR.parent
sys.path.insert(0, str(API_DIR))

# The standalone Alembic CLI does not import main.py, so it must load the same
# root environment files itself. .env.local has precedence over .env, while
# already-exported process variables retain normal dotenv precedence.
if os.getenv("MELOOHA_SKIP_DOTENV") != "1":
    load_dotenv(PROJECT_ROOT / ".env.local")
    load_dotenv(PROJECT_ROOT / ".env")

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: F401,E402
from app.db.session import _connect_args, configured_migration_database_url  # noqa: E402

config = context.config
LOGGER = logging.getLogger("melooha.database.migrations")
if config.config_file_name is not None:
    # Alembic runs inside Uvicorn at startup; keep uvicorn's error logger active
    # so startup completion and any lifespan failures remain visible.
    fileConfig(config.config_file_name, disable_existing_loggers=False)
environment_url = configured_migration_database_url()
if environment_url:
    config.set_main_option("sqlalchemy.url", environment_url.replace("%", "%%"))
    url_source = "DATABASE_URL_UNPOOLED" if os.getenv("DATABASE_URL_UNPOOLED", "").strip() else "DATABASE_URL"
    LOGGER.info("Alembic using %s for migrations", url_source)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
        connect_args=_connect_args(database_url),
    )
    LOGGER.info("Migration database connection starting")
    try:
        with connectable.connect() as connection:
            LOGGER.info("Migration database connection established")
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    except Exception:
        LOGGER.exception("Migration database connection or upgrade failed")
        raise
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
