import pytest
from api.app.llm.groq import LLMAnswer
import app.db.router as db_router
from decimal import Decimal
from sqlalchemy.engine import make_url
from sqlalchemy import select
from app.db.models import AppEvent
from app.db.session import get_session_factory
from app.db.session import _connect_args, _normalize_database_url


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "llm_configured" in response.json()


def test_chart_endpoint_returns_pydantic_chart_and_facts(client):
    response = client.post(
        "/chart/calculate",
        json={
            "birth_date": "2003-12-03",
            "birth_time": "06:43:00",
            "location": "Dhule, Maharashtra, India",
            "latitude": 20.9042,
            "longitude": 74.7749,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lagna_sign"] == "Scorpio"
    assert len(body["planets"]) == 9
    assert body["current_mahadasha"]["lord"] == "Ketu"
    assert body["current_antardasha"]["lord"] == "Venus"
    assert body["facts"][0] == "F001 : Lagna is Scorpio"


def test_signup_question_charge_and_insufficient_wallet_are_atomic(client):
    signup = client.post("/auth/register", json={"email": "chart-test@example.com", "password": "a-strong-test-password"})
    assert signup.status_code == 201, signup.text
    assert signup.json()["question_balance"] == 1
    assert "melooha_session" in signup.cookies
    assert client.get("/auth/me").json()["user"]["email"] == "chart-test@example.com"

    question_body = {
        "question_text": "What does my chart say about work?",
        "answer_text": "Jupiter is in the tenth house.",
        "facts_used": ["F006 : Jupiter in house 10 (Leo)"],
        "llm_provider": "groq",
        "llm_model": "test-model",
        "prompt_tokens": 25,
        "completion_tokens": 40,
        "total_tokens": 65,
        "cost_usd": "0.00001234",
    }
    saved = client.post("/questions", json=question_body)
    assert saved.status_code == 201, saved.text
    assert saved.json()["wallet_balance"] == 0
    assert saved.json()["facts_used"] == question_body["facts_used"]
    assert client.get("/wallet").json() == {"balance": 0}

    refused = client.post("/questions", json=question_body)
    assert refused.status_code == 409
    assert len(client.get("/questions").json()) == 1
    ledger = client.get("/wallet/ledger").json()
    assert [entry["amount"] for entry in reversed(ledger)] == [1, -1]
    assert ledger[0]["question_id"] == saved.json()["id"]

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401
    login = client.post("/auth/login", json={"email": "chart-test@example.com", "password": "a-strong-test-password"})
    assert login.status_code == 200
    assert login.json()["question_balance"] == 0


def test_dummy_credit_adds_ten_ledgered_questions(client):
    signup = client.post("/auth/register", json={"email": "dummy@example.com", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    from app.db.dummy_credit import add_dummy_questions

    assert add_dummy_questions("dummy@example.com") == 11
    assert client.get("/wallet").json() == {"balance": 11}
    ledger = client.get("/wallet/ledger").json()
    assert [entry["amount"] for entry in reversed(ledger)] == [1, 10]


def test_ask_route_uses_computed_facts_and_persists_groq_usage(client, monkeypatch):
    signup = client.post("/auth/register", json={"email": "ask-test@example.com", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    captured = {}

    def fake_generate(question, facts):
        captured["question"] = question
        captured["facts"] = facts
        return LLMAnswer(
            answer="Jupiter occupies the tenth house in Leo.",
            provider="groq",
            model="openai/gpt-oss-20b",
            api_key_slot="GROQ_API_KEY_3",
            prompt_tokens=50,
            completion_tokens=12,
            total_tokens=62,
            estimated_cost_usd=Decimal("0.00000735"),
            usage_is_estimated=False,
            succeeded=True,
        )

    monkeypatch.setattr(db_router, "generate_answer", fake_generate)
    response = client.post("/questions/ask", json={
        "question_text": "What is the career significance of Jupiter?",
        "chart": {
            "birth_date": "2003-12-03",
            "birth_time": "06:43:00",
            "location": "Dhule, Maharashtra, India",
            "latitude": 20.9042,
            "longitude": 74.7749,
        },
    })

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["answer_text"] == "Jupiter occupies the tenth house in Leo."
    assert body["llm_provider"] == "groq"
    assert body["llm_model"] == "openai/gpt-oss-20b"
    assert body["api_key_slot"] == "GROQ_API_KEY_3"
    assert body["total_tokens"] == 62
    assert body["cost_usd"] == "0.00000735"
    assert body["wallet_balance"] == 0
    assert any("Jupiter in house 10 (Leo)" in fact for fact in captured["facts"])
    assert body["facts_used"] == captured["facts"]
    assert client.get("/wallet/ledger").json()[0]["question_id"] == body["id"]
    with get_session_factory()() as session:
        events = set(session.scalars(select(AppEvent.event).where(AppEvent.user_id == signup.json()["user"]["id"])).all())
    assert {"signup", "first_question"} <= events


def test_ask_route_returns_friendly_fallback_without_spending(client, monkeypatch):
    signup = client.post("/auth/register", json={"email": "offline-test@example.com", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    monkeypatch.setattr(db_router, "generate_answer", lambda *_: LLMAnswer(
        answer="Astrology answers are temporarily unavailable. Please try again in a little while.",
        provider="groq", model="openai/gpt-oss-20b", api_key_slot=None,
        prompt_tokens=0, completion_tokens=0, total_tokens=0,
        estimated_cost_usd=Decimal("0"), usage_is_estimated=False, succeeded=False,
    ))
    response = client.post("/questions/ask", json={
        "question_text": "What does my chart say?",
        "chart": {
            "birth_date": "2003-12-03",
            "birth_time": "06:43:00",
            "location": "Dhule, Maharashtra, India",
            "latitude": 20.9042,
            "longitude": 74.7749,
        },
    })
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
    assert client.get("/wallet").json() == {"balance": 1}
    assert client.get("/questions").json() == []


def _profile_payload():
    return {
        "display_name": "Test user",
        "birth_date": "2003-12-03",
        "birth_time": "06:43:00",
        "location": "Dhule, Maharashtra, India",
        "latitude": 20.9042,
        "longitude": 74.7749,
        "label": "Private test chart",
    }


def test_neon_database_urls_use_pg8000_and_python_ssl():
    normalized = _normalize_database_url(
        "postgresql://user:pass@db.example.test/app?sslmode=require&channel_binding=require"
    )
    parsed = make_url(normalized)
    assert parsed.drivername == "postgresql+pg8000"
    assert "sslmode" not in parsed.query
    assert "channel_binding" not in parsed.query
    connect_args = _connect_args(normalized)
    assert connect_args["ssl_context"].check_hostname is True
    assert connect_args["timeout"] == 15


def test_sqlite_test_database_does_not_receive_postgres_connect_args():
    assert _normalize_database_url("sqlite:///test.db") == "sqlite:///test.db"
    assert _connect_args("sqlite:///test.db") == {}


def _fake_success_answer(facts):
    return LLMAnswer(
        answer="Jupiter may suggest a thoughtful tendency in house 10 (Leo) [F006].",
        provider="gemini",
        model="gemini-3.5-flash-lite",
        api_key_slot="GEMINI_API_KEY",
        prompt_tokens=40,
        completion_tokens=18,
        total_tokens=58,
        estimated_cost_usd=Decimal("0.000057"),
        usage_is_estimated=False,
        succeeded=True,
    )


def _sse_events(response):
    import json

    events = []
    current_event = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: ") and current_event:
            events.append((current_event, json.loads(line[6:])))
            current_event = None
    return events


def test_streaming_ask_saves_checked_answer_facts_and_wallet_charge(client, monkeypatch):
    signup = client.post("/auth/register", json={"email": "stream@example.com", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    saved_profile = client.post("/profile", json=_profile_payload())
    assert saved_profile.status_code == 200, saved_profile.text
    captured = {}

    def fake_generate(question, facts, **kwargs):
        captured["question"] = question
        captured["facts"] = facts
        captured["kwargs"] = kwargs
        return _fake_success_answer(facts)

    monkeypatch.setattr(db_router, "generate_answer", fake_generate)
    response = client.post("/ask", json={"question_text": "What does Jupiter suggest for my career?"})

    assert response.status_code == 200, response.text
    events = _sse_events(response)
    assert [name for name, _ in events][-1] == "complete"
    complete = events[-1][1]
    assert complete["status"] == "answered"
    assert complete["wallet_balance"] == 0
    assert complete["facts_used"] == captured["facts"]
    assert any("Jupiter in house 10 (Leo)" in fact for fact in complete["facts_used"])
    assert captured["question"] == "What does Jupiter suggest for my career?"
    assert captured["kwargs"]["stream"] is True
    assert client.get("/wallet").json() == {"balance": 0}
    history = client.get("/history")
    assert history.status_code == 200
    assert history.json()[0]["facts_used"] == complete["facts_used"]
    assert history.json()[0]["llm_provider"] == "gemini"
    assert client.get("/me").json()["question_balance"] == 0


def test_streaming_ask_refunds_credit_and_writes_refund_ledger(client, monkeypatch):
    signup = client.post("/auth/register", json={"email": "refund@example.com", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    assert client.post("/profile", json=_profile_payload()).status_code == 200
    monkeypatch.setattr(db_router, "generate_answer", lambda *_args, **_kwargs: LLMAnswer(
        answer="Astrology answers are temporarily unavailable. Please try again in a little while.",
        provider="none", model="gemini-3.5-flash-lite", api_key_slot=None,
        prompt_tokens=10, completion_tokens=0, total_tokens=10,
        estimated_cost_usd=Decimal("0"), usage_is_estimated=False, succeeded=False,
    ))

    response = client.post("/ask", json={"question_text": "What might my chart suggest?"})
    assert response.status_code == 200
    events = _sse_events(response)
    assert events[-1][0] == "failed"
    assert events[-1][1]["wallet_balance"] == 1
    assert client.get("/wallet").json() == {"balance": 1}
    ledger = client.get("/wallet/ledger").json()
    assert [row["amount"] for row in reversed(ledger)] == [1, -1, 1]
    assert ledger[0]["reason"] == "refund"
    assert "question #" in ledger[0]["note"]
    assert client.get("/history").json()[0]["status"] == "failed"


def test_retrying_a_refunded_failure_does_not_spend_a_second_credit(client, monkeypatch):
    assert client.post("/auth/register", json={"email": "retry@example.com", "password": "a-strong-test-password"}).status_code == 201
    assert client.post("/profile", json=_profile_payload()).status_code == 200
    monkeypatch.setattr(db_router, "generate_answer", lambda *_args, **_kwargs: LLMAnswer(
        answer="Friendly provider fallback", provider="none", model="test-model", api_key_slot=None,
        prompt_tokens=4, completion_tokens=0, total_tokens=4, estimated_cost_usd=Decimal("0"),
        usage_is_estimated=False, succeeded=False,
    ))
    first = client.post("/ask", json={"question_text": "When might my career gain momentum?"})
    failed = _sse_events(first)[-1][1]
    assert first.status_code == 200
    assert client.get("/wallet").json()["balance"] == 1
    ledger_before_retry = client.get("/wallet/ledger").json()

    monkeypatch.setattr(db_router, "generate_answer", lambda _question, facts, **_kwargs: _fake_success_answer(facts))
    retry = client.post("/ask", json={"retry_id": failed["question_id"]})
    events = _sse_events(retry)
    assert retry.status_code == 200
    assert events[0][0] == "started"
    assert events[-1][0] == "complete"
    assert client.get("/wallet").json()["balance"] == 1
    assert client.get("/wallet/ledger").json() == ledger_before_retry
    assert client.get("/history").json()[0]["status"] == "answered"


def test_out_of_balance_saves_draft_and_never_calls_llm(client, monkeypatch):
    signup = client.post("/auth/register", json={"email": "draft@example.com", "password": "a-strong-test-password"})
    assert signup.status_code == 201
    assert client.post("/wallet/spend").json() == {"balance": 0}
    monkeypatch.setattr(db_router, "generate_answer", lambda *_args, **_kwargs: pytest.fail("LLM must not be called"))

    question = "Could you answer this after I add credits?"
    response = client.post("/ask", json={"question_text": question})
    assert response.status_code == 402
    assert response.json()["status"] == "out_of_balance"
    assert response.json()["question_text"] == question
    saved = client.get("/history").json()[0]
    assert saved["question_text"] == question
    assert saved["answer_text"] is None
    assert saved["status"] == "draft"
    assert client.get("/wallet").json() == {"balance": 0}

    add = client.post("/wallet/add", json={"amount": 10})
    assert add.status_code == 200
    assert add.json() == {"balance": 10}
    assert client.post("/profile", json=_profile_payload()).status_code == 200
    monkeypatch.setattr(db_router, "generate_answer", lambda _question, facts, **_kwargs: _fake_success_answer(facts))
    resumed = client.post("/ask", json={"draft_id": saved["id"]})
    assert resumed.status_code == 200
    assert _sse_events(resumed)[-1][1]["question_id"] == saved["id"]
    assert client.get("/history").json()[0]["status"] == "answered"
    assert client.get("/wallet").json() == {"balance": 9}


def test_history_is_scoped_to_logged_in_user(client, monkeypatch):
    first = client.post("/auth/register", json={"email": "first-history@example.com", "password": "a-strong-test-password"})
    assert first.status_code == 201
    assert client.post("/profile", json=_profile_payload()).status_code == 200
    monkeypatch.setattr(db_router, "generate_answer", lambda _question, facts, **_kwargs: _fake_success_answer(facts))
    asked = client.post("/ask", json={"question_text": "What does Jupiter suggest?"})
    assert asked.status_code == 200
    first_history = client.get("/history").json()
    assert len(first_history) == 1
    first_id = first_history[0]["id"]

    assert client.post("/auth/logout").status_code == 204
    second = client.post("/auth/register", json={"email": "second-history@example.com", "password": "a-strong-test-password"})
    assert second.status_code == 201
    assert client.get(f"/history?question_id={first_id}").json() == []
