from types import SimpleNamespace

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


def test_gemini_fallback_after_groq_key_failure_uses_only_question_and_chart_facts():
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


def test_gemini_failure_returns_friendly_failure_without_raw_error(caplog):
    gemini = FakeGeminiClient([RuntimeError("secret credential details")])
    answer = generate_answer(
        "What does the chart suggest?",
        ["F001 : Lagna is Scorpio"],
        api_keys=[],
        gemini_api_key="fake-gemini-key",
        gemini_client_factory=lambda _: gemini,
    )
    assert answer.succeeded is True
    assert answer.provider == "fallback"
    assert "temporarily unavailable" not in answer.answer
    assert "secret credential details" not in caplog.text
