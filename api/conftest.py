import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

# Prevent app/Alembic imports during tests from loading any local .env file.
os.environ["MELOOHA_SKIP_DOTENV"] = "1"

from main import app
from app.db.base import Base
from app.db.session import _engine_for_url, _normalize_database_url


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_url = os.getenv("TEST_DATABASE_URL", "").strip() or f"sqlite:///{tmp_path / 'isolated-test.db'}"
    configured_url = _normalize_database_url(test_url)
    real_url = _normalize_database_url(os.getenv("DATABASE_URL", ""))
    if real_url and configured_url == real_url:
        pytest.fail("TEST_DATABASE_URL must be separate from DATABASE_URL; refusing to use the application database.")
    monkeypatch.setenv("TEST_DATABASE_URL", test_url)
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "")
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-at-least-32-characters-long")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MELOOHA_SKIP_DOTENV", "1")
    _engine_for_url.cache_clear()
    with TestClient(app) as test_client:
        engine = _engine_for_url(configured_url)
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(delete(table))
        yield test_client
    _engine_for_url.cache_clear()
