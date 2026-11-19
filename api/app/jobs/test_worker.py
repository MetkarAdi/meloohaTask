from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import OperationalError

from sqlalchemy import func, select

from app.db.models import AppEvent, DailyInsight, InsightJob
from app.db.session import get_session_factory
from app.jobs import worker


def test_worker_recognizes_missing_jobs_table_without_matching_other_db_errors():
    missing_jobs = OperationalError("SELECT", {}, RuntimeError('relation "jobs" does not exist'))
    missing_other = OperationalError("SELECT", {}, RuntimeError('relation "users" does not exist'))
    assert worker._is_jobs_table_missing(missing_jobs)
    assert not worker._is_jobs_table_missing(missing_other)


def _register_and_profile(client, email):
    assert client.post("/auth/register", json={"email": email, "password": "a-strong-test-password"}).status_code == 201
    return client.post("/profile", json={
        "display_name": "Demo", "birth_date": "2003-12-03", "birth_time": "06:43:00",
        "timezone": "Asia/Kolkata", "location": "Dhule, Maharashtra, India",
        "latitude": 20.9042, "longitude": 74.7749,
    })


def _fake_insight(_user_id, _run_date):
    return (
        "The supplied transits may invite reflection [F001][M017].",
        ["F001 : Transiting Jupiter in house 10 (Leo)", "M017 : Jupiter is associated with growth."],
        "test", "test-model",
    )


def _jobs_for(user_id):
    with get_session_factory()() as session:
        return session.scalars(select(InsightJob).where(InsightJob.user_id == user_id)).all()


def test_scheduler_and_worker_are_idempotent_for_a_user_day(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET", "test-admin-secret")
    signup = client.post("/auth/register", json={"email": "daily-one@example.test", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    user_id = signup.json()["user"]["id"]
    assert client.post("/profile", json={
        "display_name": "Demo", "birth_date": "2003-12-03", "birth_time": "06:43:00",
        "timezone": "Asia/Kolkata", "location": "Dhule, Maharashtra, India",
        "latitude": 20.9042, "longitude": 74.7749,
    }).status_code == 200
    assert _register_and_profile(client, "daily-other@example.test").status_code == 200

    headers = {"ADMIN_SECRET": "test-admin-secret"}
    first = client.post("/admin/schedule-insights", headers=headers)
    second = client.post("/admin/schedule-insights", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["jobs_added"] == 2
    assert second.json()["jobs_added"] == 0
    job = _jobs_for(user_id)[0]

    monkeypatch.setattr(worker, "_generate", _fake_insight)
    result = worker.process_job(job.id, force=True)
    repeated = worker.process_job(job.id, force=True)
    assert result and repeated
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(DailyInsight.id)).where(DailyInsight.user_id == user_id)) == 1
        saved_job = session.get(InsightJob, job.id)
        assert saved_job.status == "completed"
        assert saved_job.attempts == 1


def test_interrupted_persistence_retries_with_one_insight(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET", "test-admin-secret")
    signup = client.post("/auth/register", json={"email": "daily-retry@example.test", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    user_id = signup.json()["user"]["id"]
    assert client.post("/profile", json={
        "display_name": "Demo", "birth_date": "2003-12-03", "birth_time": "06:43:00",
        "timezone": "Asia/Kolkata", "location": "Dhule, Maharashtra, India",
        "latitude": 20.9042, "longitude": 74.7749,
    }).status_code == 200
    client.post("/admin/schedule-insights", headers={"ADMIN_SECRET": "test-admin-secret"})
    job = _jobs_for(user_id)[0]
    monkeypatch.setattr(worker, "_generate", _fake_insight)

    def interrupt_after_insert(_session, _insight):
        raise RuntimeError("simulated worker termination during persistence")

    assert worker.process_job(job.id, force=True, persist_hook=interrupt_after_insert) is None
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(DailyInsight.id)).where(DailyInsight.user_id == user_id)) == 0
        failed = session.get(InsightJob, job.id)
        assert failed.status == "failed"
        assert failed.attempts == 1
        retry_at = failed.next_attempt_at.replace(tzinfo=timezone.utc) if failed.next_attempt_at.tzinfo is None else failed.next_attempt_at
        assert retry_at > datetime.now(timezone.utc)

    result = worker.process_job(job.id, force=True)
    assert result is not None
    assert worker.process_job(job.id, force=True) is not None
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(DailyInsight.id)).where(DailyInsight.user_id == user_id)) == 1
        retried = session.get(InsightJob, job.id)
        assert retried.status == "completed"
        assert retried.attempts == 2


def test_crashed_running_job_is_reclaimed_after_its_lease(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET", "test-admin-secret")
    signup = client.post("/auth/register", json={"email": "daily-killed@example.test", "password": "a-strong-test-password"})
    user_id = signup.json()["user"]["id"]
    assert client.post("/profile", json={
        "display_name": "Demo", "birth_date": "2003-12-03", "birth_time": "06:43:00",
        "timezone": "Asia/Kolkata", "location": "Dhule, Maharashtra, India",
        "latitude": 20.9042, "longitude": 74.7749,
    }).status_code == 200
    client.post("/admin/schedule-insights", headers={"ADMIN_SECRET": "test-admin-secret"})
    job = _jobs_for(user_id)[0]
    claimed_at = datetime.now(timezone.utc) - timedelta(seconds=worker.LEASE_SECONDS + 1)
    claimed = worker._claim_job(job.id, now=claimed_at)
    assert claimed is not None  # The previous worker had claimed the row before dying.
    monkeypatch.setattr(worker, "_generate", _fake_insight)

    recovered = worker.process_job(job.id)
    assert recovered is not None
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(DailyInsight.id)).where(DailyInsight.user_id == user_id)) == 1
        finished = session.get(InsightJob, job.id)
        assert finished.status == "completed"
        assert finished.attempts == 2


def test_today_endpoint_generates_lazily_and_logs_sessions_and_metrics(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET", "test-admin-secret")
    signup = client.post("/auth/register", json={"email": "daily-lazy@example.test", "password": "a-strong-test-password"})
    user_id = signup.json()["user"]["id"]
    assert client.post("/profile", json={
        "display_name": "Demo", "birth_date": "2003-12-03", "birth_time": "06:43:00",
        "timezone": "Asia/Kolkata", "location": "Dhule, Maharashtra, India",
        "latitude": 20.9042, "longitude": 74.7749,
    }).status_code == 200
    seen = {}

    def generate(question, facts, *, stream=False):
        seen["question"] = question
        seen["facts"] = facts
        return type("Result", (), {"succeeded": True, "answer": "A short grounded note [F001][M017].", "provider": "test", "model": "test"})()

    monkeypatch.setattr(worker, "calculate_chart", lambda _request, as_of=None: type("Chart", (), {"facts": [
        "F001 : Lagna is Scorpio", "F002 : Transiting Jupiter in house 10 (Leo)",
        "F003 : Transiting Saturn in house 5 (Pisces)",
    ]})())
    monkeypatch.setattr(worker, "generate_answer", generate)
    assert client.post("/events", json={"event": "session_start"}).status_code == 201
    today = client.get("/insight/today")
    assert today.status_code == 200, today.text
    assert today.json()["answer_text"] == "A short grounded note [F001][M017]."
    assert any("Transiting Jupiter" in fact for fact in seen["facts"])
    assert any("Transiting Saturn" in fact for fact in seen["facts"])
    assert any(fact.startswith("M") for fact in seen["facts"])
    assert client.get("/insight/today").json()["id"] == today.json()["id"]

    assert client.post("/events", json={"event": "home_viewed"}).status_code == 201
    client.post("/events", json={"event": "insight_viewed"})
    client.post("/events", json={"event": "facts_sheet_opened"})
    metrics = client.get("/admin/metrics", headers={"ADMIN_SECRET": "test-admin-secret"})
    assert metrics.status_code == 200
    assert metrics.json()["share_viewed_insight"]["users"] == 1
    assert metrics.json()["share_opened_facts_sheet"]["users"] == 1
    with get_session_factory()() as session:
        names = set(session.scalars(select(AppEvent.event).where(AppEvent.user_id == user_id)).all())
    assert {"signup", "session_start", "home_viewed", "insight_viewed", "facts_sheet_opened"} <= names


def test_admin_metrics_requires_secret_and_computes_day_returns(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET", "test-admin-secret")
    assert client.get("/admin/metrics").status_code == 403
    assert client.get("/admin/metrics", headers={"ADMIN_SECRET": "wrong"}).status_code == 403
    users = []
    for index in range(2):
        response = client.post("/auth/register", json={"email": f"metrics-{index}@example.test", "password": "a-strong-test-password"})
        users.append(response.json()["user"]["id"])

    today = datetime.now(timezone.utc).date()
    signup_date = today - timedelta(days=8)
    with get_session_factory()() as session, session.begin():
        for index, user_id in enumerate(users):
            session.add(AppEvent(user_id=user_id, event="signup", timestamp=datetime.combine(signup_date, datetime.min.time(), timezone.utc)))
            if index == 0:
                session.add_all([
                    AppEvent(user_id=user_id, event="session_start", timestamp=datetime.combine(signup_date + timedelta(days=1), datetime.min.time(), timezone.utc)),
                    AppEvent(user_id=user_id, event="session_start", timestamp=datetime.combine(signup_date + timedelta(days=7), datetime.min.time(), timezone.utc)),
                    AppEvent(user_id=user_id, event="insight_viewed", timestamp=datetime.now(timezone.utc)),
                    AppEvent(user_id=user_id, event="facts_sheet_opened", timestamp=datetime.now(timezone.utc)),
                ])
    result = client.get("/admin/metrics", headers={"ADMIN_SECRET": "test-admin-secret"}).json()
    assert result["day_1_return_rate"] == {"rate": 0.5, "users": 1, "eligible_users": 2}
    assert result["day_7_return_rate"] == {"rate": 0.5, "users": 1, "eligible_users": 2}
    assert result["share_viewed_insight"]["rate"] == 0.5
    assert result["share_opened_facts_sheet"]["rate"] == 0.5
