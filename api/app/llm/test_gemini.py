from types import SimpleNamespace
import logging

import pytest

from api.app.llm.groq import APIKey, generate_answer


def stream(text, prompt_tokens=100, output_tokens=20):
    return [
        SimpleNamespace(text=text, usage_metadata=None),
        SimpleNamespace(
            text=None,
            usage_metadata=SimpleNamespace(
                prompt_token_count=prompt_tokens,
                candidates_token_count=output_tokens,
                total_token_count=prompt_tokens + output_tokens,
            ),
        ),
    ]


class FakeGeminiModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate_content_stream(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class FakeGeminiClient:
    def __init__(self, responses):
        self.models = FakeGeminiModels(responses)

    def close(self):
        pass


class ProviderStatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"private provider detail {status_code}")
        self.status_code = status_code


def test_gemini_primary_uses_only_question_and_chart_facts_and_skips_groq():
    facts = ["F001 : Lagna is Scorpio", "F005 : Jupiter in house 10 (Leo), direct, nakshatra Magha"]
    gemini = FakeGeminiClient([stream("Jupiter may suggest a tendency for thoughtful growth [F005][F001].")])
    answer = generate_answer(
        "What does Jupiter suggest?",
        facts,
        api_keys=[APIKey("GROQ_API_KEY", "fake-groq-key")],
        client_factory=lambda _: (_ for _ in ()).throw(TimeoutError("private detail")),
        gemini_api_key="fake-gemini-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_client_factory=lambda _: gemini,
        stream=True,
    )

    assert answer.succeeded is True
    assert answer.provider == "gemini"
    assert answer.model == "gemini-3.5-flash-lite"
    assert answer.api_key_slot == "GEMINI_API_KEY"
    assert answer.prompt_tokens == 100
    assert answer.completion_tokens == 20
    sent = gemini.models.calls[0]
    assert sent["contents"].startswith("Question:\nWhat does Jupiter suggest?\n\nVerified chart facts:\n[")
    assert "F005 : Jupiter in house 10 (Leo)" in sent["contents"]
    assert "M017 : In Vedic astrology, Jupiter is associated with learning" in sent["contents"]
    assert "email" not in sent["contents"].lower()
    assert "name" not in sent["contents"].lower()
    assert "GEMINI_API_KEY" not in sent["contents"]
    assert sent["config"].system_instruction


def test_gemini_retries_validation_failure_then_returns_corrected_answer():
    facts = ["F007 : Saturn in house 6 (Pisces), retrograde, nakshatra Revati"]
    gemini = FakeGeminiClient([
        stream("Saturn may be in house 8 [F007]."),
        stream("Saturn may suggest a reflective tendency in house 6 (Pisces) [F007][M019].", 120, 30),
    ])
    answer = generate_answer(
        "What does Saturn suggest?",
        facts,
        api_keys=[],
        gemini_api_key="fake-gemini-key",
        gemini_client_factory=lambda _: gemini,
        stream=True,
    )

    assert answer.succeeded is True
    assert "house 6" in answer.answer
    assert "house 8" not in answer.answer
    assert len(gemini.models.calls) == 2
    assert "Validation feedback" in gemini.models.calls[1]["contents"]
    assert answer.total_tokens == 270


def test_gemini_failure_falls_through_to_graceful_error_without_raw_error(caplog):
    gemini = FakeGeminiClient([RuntimeError("secret credential details")])
    answer = generate_answer(
        "What does the chart suggest?",
        ["F001 : Lagna is Scorpio"],
        api_keys=[],
        gemini_api_key="fake-gemini-key",
        gemini_client_factory=lambda _: gemini,
    )
    assert answer.succeeded is False
    assert answer.provider == "none"
    assert "temporarily unavailable" in answer.answer
    assert "secret credential details" not in caplog.text


@pytest.mark.parametrize("gemini_error,retry_limit", [
    (ProviderStatusError(429), "0"),
    (TimeoutError("private timeout details"), "0"),
    (ProviderStatusError(500), "0"),
    (ProviderStatusError(401), "1"),
    (ProviderStatusError(400), "1"),
])
def test_gemini_errors_fall_through_to_groq_without_retrying_invalid_requests(gemini_error, retry_limit, monkeypatch, caplog):
    from api.app.llm.groq import APIKey

    monkeypatch.setenv("GEMINI_MAX_TRANSIENT_RETRIES", retry_limit)
    monkeypatch.setenv("LLM_RETRY_BASE_DELAY_SECONDS", "0")
    facts = ["F005 : Jupiter in house 10 (Leo), direct, nakshatra Magha"]
    gemini = FakeGeminiClient([gemini_error])
    groq_calls = []
    answer_text = "Jupiter may support learning and perspective [F005][M017]."
    groq_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=answer_text))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=10),
    )

    class FakeGroqCompletions:
        def create(self, **kwargs):
            groq_calls.append(kwargs)
            return groq_response

    class FakeGroqClient:
        chat = SimpleNamespace(completions=FakeGroqCompletions())

        def close(self):
            pass

    with caplog.at_level(logging.WARNING):
        answer = generate_answer(
            "What does Jupiter suggest?", facts,
            api_keys=[APIKey("GROQ_API_KEY", "private-groq-key")],
            client_factory=lambda _: FakeGroqClient(),
            gemini_api_key="private-gemini-key",
            gemini_client_factory=lambda _: gemini,
            stream=False,
        )

    assert answer.succeeded is True
    assert answer.provider == "groq"
    assert len(gemini.models.calls) == (2 if retry_limit == "1" and isinstance(gemini_error, ProviderStatusError) and gemini_error.status_code == 500 else 1)
    assert len(groq_calls) == 1
    assert "private-groq-key" not in caplog.text
    assert "private-gemini-key" not in caplog.text
    assert "private provider detail" not in caplog.text


def test_gemini_transient_retry_uses_exponential_backoff_then_keeps_primary(monkeypatch):
    monkeypatch.setenv("GEMINI_MAX_TRANSIENT_RETRIES", "1")
    monkeypatch.setenv("LLM_RETRY_BASE_DELAY_SECONDS", "0.25")
    delays = []
    monkeypatch.setattr("api.app.llm.gemini.time.sleep", delays.append)
    facts = ["F005 : Jupiter in house 10 (Leo), direct, nakshatra Magha"]
    gemini = FakeGeminiClient([
        ProviderStatusError(503),
        stream("Jupiter may support learning and perspective [F005][M017]."),
    ])
    answer = generate_answer(
        "What does Jupiter suggest?", facts,
        api_keys=[], gemini_api_key="private-gemini-key",
        gemini_client_factory=lambda _: gemini,
    )
    assert answer.succeeded and answer.provider == "gemini"
    assert len(gemini.models.calls) == 2
    assert delays == [0.25]


def test_gemini_sdk_timeout_is_configured_and_sdk_retries_are_disabled(monkeypatch):
    from google import genai

    from api.app.llm import gemini as gemini_provider

    captured = {}
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: captured.update(kwargs) or object())
    gemini_provider._default_client("private-key")
    assert captured["http_options"]["timeout"] == 7500
    assert captured["http_options"]["retry_options"]["attempts"] == 1
