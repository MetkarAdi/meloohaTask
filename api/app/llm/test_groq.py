import logging
from types import SimpleNamespace

from api.app.llm.groq import APIKey, FALLBACK_MESSAGE, generate_answer
from api.app.llm.groq import _messages
from api.app.llm.validation import safe_fact_answer, validate_answer
from api.app.llm.routing import route_question


class FakeHTTPError(Exception):
    def __init__(self, status_code):
        super().__init__(f"sensitive detail should not be logged: {status_code}")
        self.status_code = status_code


def usage(prompt=120, completion=80):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)


def complete(text="Scorpio lagna may suggest a reflective tendency [F001][M034].", token_usage=None):
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=token_usage or usage())


def chunk(text=None, token_usage=None):
    choices = [] if text is None else [SimpleNamespace(delta=SimpleNamespace(content=text))]
    return SimpleNamespace(choices=choices, usage=token_usage)


class FakeCompletionResource:
    def __init__(self, action, calls):
        self.action = action
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.action, Exception):
            raise self.action
        if callable(self.action):
            return self.action()
        return self.action


class FakeClient:
    def __init__(self, action, calls):
        self.chat = SimpleNamespace(completions=FakeCompletionResource(action, calls))


def make_keys():
    return [APIKey(f"GROQ_API_KEY{('_' + str(i)) if i > 1 else ''}", f"secret-{i}") for i in range(1, 5)]


def test_answer_prompt_requires_the_users_language_for_the_whole_response():
    prompt = _messages("¿Cuándo podría avanzar en mi trabajo?", ["F001 : Lagna is Scorpio"])
    assert "Detect the language of the user's question" in prompt[0]["content"]
    assert "same language" in prompt[0]["content"]
    assert "do not switch to English" in prompt[0]["content"]


def fake_factory(script, per_key_calls):
    return lambda secret: FakeClient(script[secret], per_key_calls.setdefault(secret, []))


def test_timeout_and_http_errors_rotate_keys_then_log_only_key_slot(caplog):
    keys = make_keys()
    calls = {}
    script = {
        "secret-1": TimeoutError("never expose this secret detail"),
        "secret-2": FakeHTTPError(429),
        "secret-3": FakeHTTPError(503),
        "secret-4": complete("Scorpio lagna may suggest a reflective tendency [F001][M034].", usage(100, 30)),
    }
    with caplog.at_level(logging.INFO, logger="melooha.llm.groq"):
        answer = generate_answer(
            "What do the facts say?", ["F001 : Lagna is Scorpio"],
            api_keys=keys, client_factory=fake_factory(script, calls), stream=False,
        )

    assert answer.succeeded is True
    assert answer.answer == "Scorpio lagna may suggest a reflective tendency [F001][M034]."
    assert answer.api_key_slot == "GROQ_API_KEY_4"
    assert (answer.prompt_tokens, answer.completion_tokens, answer.total_tokens) == (100, 30, 130)
    assert str(answer.estimated_cost_usd) == "0.0000165"
    assert [key for key in calls] == ["secret-1", "secret-2", "secret-3", "secret-4"]
    assert "GROQ_API_KEY_4" in caplog.text
    assert all(secret not in caplog.text for secret in script)
    assert "never expose this secret detail" not in caplog.text


def test_empty_answer_retries_then_uses_gemini():
    keys = make_keys()[:1]
    calls = {}
    script = {"secret-1": _scripted(complete(text="  ", token_usage=usage(100, 0)), complete(text="  ", token_usage=usage(100, 0)))}
    from api.app.llm.test_gemini import FakeGeminiClient, stream
    gemini = FakeGeminiClient([stream("Jupiter may suggest thoughtful growth [F001][M017].")])
    answer = generate_answer(
        "What does Jupiter suggest?", ["F001 : Jupiter in house 10 (Leo)"],
        api_keys=keys, client_factory=fake_factory(script, calls), stream=False,
        gemini_api_key="fake-gemini", gemini_client_factory=lambda _: gemini,
    )
    assert answer.succeeded is True
    assert answer.provider == "gemini"
    assert len(calls["secret-1"]) == 2
    assert len(gemini.models.calls) == 1


def test_mid_stream_failure_discards_partial_text_and_retries_whole_answer():
    keys = make_keys()[:2]
    calls = {}

    def broken_stream():
        yield chunk("Partial answer that must not escape. ")
        raise TimeoutError("stream read failed")

    script = {
        "secret-1": broken_stream(),
        "secret-2": [chunk("Sun in house 1 (Scorpio) may indicate a tendency toward expression [F002][M013]."), chunk(token_usage=usage(90, 12))],
    }
    answer = generate_answer(
        "Question", ["F002 : Sun in house 1 (Scorpio)"],
        api_keys=keys, client_factory=fake_factory(script, calls), stream=True,
    )
    assert answer.succeeded is True
    assert answer.answer == "Sun in house 1 (Scorpio) may indicate a tendency toward expression [F002][M013]."
    assert "Partial answer" not in answer.answer
    assert answer.api_key_slot == "GROQ_API_KEY_2"
    assert answer.prompt_tokens >= 90
    assert answer.completion_tokens > 12  # includes the discarded partial attempt
    assert calls["secret-2"][0]["stream"] is True
    assert calls["secret-2"][0]["extra_body"] == {"stream_options": {"include_usage": True}}


def test_all_failures_return_friendly_message_without_raw_provider_errors(caplog):
    keys = make_keys()
    calls = {}
    script = {f"secret-{i}": FakeHTTPError(500) for i in range(1, 5)}
    with caplog.at_level(logging.WARNING, logger="melooha.llm.groq"):
        answer = generate_answer(
            "Question", ["F003 : Mercury in house 2 (Sagittarius)"],
            api_keys=keys, client_factory=fake_factory(script, calls), stream=False, gemini_api_key="",
        )

    assert answer.succeeded is True
    assert answer.provider == "fallback"
    assert "could not" not in answer.answer.lower()
    assert "500" in caplog.text
    assert "Returning grounded fallback" in caplog.text
    assert "provider_failure" in caplog.text
    assert all(secret not in caplog.text for secret in script)


def test_no_configured_keys_returns_friendly_message_and_logs_fallback_reason(caplog):
    answer = generate_answer("Question", ["F001 : Lagna is Scorpio"], api_keys=[], gemini_api_key="")
    assert answer.succeeded is True
    assert answer.provider == "fallback"
    assert "Groq: no API keys configured" in caplog.text
    assert "gemini_failure=no_api_key_configured" in caplog.text


def _scripted(*responses):
    response_iter = iter(responses)
    return lambda: next(response_iter)


def test_checker_rejects_wrong_planet_house_pair_and_retry_corrects_it():
    facts = [
        "F001 : Lagna is Scorpio",
        "F005 : Jupiter in house 10 (Leo), direct, nakshatra Magha",
        "F007 : Saturn in house 6 (Pisces), retrograde, nakshatra Revati",
    ]
    wrong = "Saturn may indicate a tendency in the 8th house [F007]."
    errors = validate_answer(wrong, facts)
    assert any("House 8" in error or "Saturn is not in house 8" in error for error in errors)
    assert any(
        "House 8" in error or "Saturn is not in house 8" in error
        for error in validate_answer("Saturn may indicate a tendency in the eighth house [F007].", facts)
    )

    calls = {}
    script = {
        "secret-1": _scripted(
            complete(wrong, usage(100, 20)),
            complete("Saturn may indicate a reflective tendency in house 6 (Pisces) [F007][M019].", usage(110, 25)),
        )
    }
    answer = generate_answer(
        "What does Saturn suggest?", facts,
        api_keys=make_keys()[:1], client_factory=fake_factory(script, calls), stream=False, gemini_api_key="",
    )

    assert answer.succeeded is True
    assert "house 6" in answer.answer
    assert "house 8" not in answer.answer
    assert len(calls["secret-1"]) == 2
    retry_messages = calls["secret-1"][1]["messages"]
    assert "Regenerate a complete answer" in retry_messages[-1]["content"]
    assert "House 8" in retry_messages[-1]["content"]


def test_checker_rejects_wrong_sign_date_unknown_citation_and_certainty():
    facts = [
        "F001 : Lagna is Scorpio",
        "F007 : Saturn in house 6 (Pisces), retrograde, nakshatra Revati",
        "F011 : Current mahadasha is Ketu from 2024-01-01 to 2031-01-01",
    ]
    answer = "Saturn will definitely be in Aries [F999] by March 2040."
    errors = validate_answer(answer, facts)
    assert any("does not exist" in error for error in errors)
    assert any("Aries" in error and "supplied" in error for error in errors)
    assert any("Date" in error for error in errors)
    assert any("Avoid guarantees" in error for error in errors)


def test_two_invalid_model_answers_return_relevant_safe_answer_and_log_violations(caplog):
    facts = [
        "F001 : Lagna is Scorpio",
        "F007 : Saturn in house 6 (Pisces), retrograde, nakshatra Revati",
    ]
    wrong_one = "Saturn may be in house 8 [F007]."
    wrong_two = "Saturn will definitely be in Aries in house 2 [F007]."
    calls = {}
    script = {"secret-1": _scripted(complete(wrong_one), complete(wrong_two))}
    with caplog.at_level(logging.WARNING, logger="melooha.llm.groq"):
        answer = generate_answer(
            "What does Saturn suggest?", facts,
            api_keys=make_keys()[:1], client_factory=fake_factory(script, calls), stream=False, gemini_api_key="",
        )

    assert answer.succeeded is True
    routed_facts = route_question("What does Saturn suggest?", facts)
    assert answer.answer == safe_fact_answer(routed_facts, "What does Saturn suggest?")
    assert "house 8" not in answer.answer
    assert "house 2" not in answer.answer
    assert "[F007]" in answer.answer
    assert validate_answer(answer.answer, routed_facts) == []
    assert "violations=" in caplog.text
    assert "Saturn in house 8 contradicts" in caplog.text
    assert f"raw_answer={wrong_two!r}" in caplog.text
    assert "Returning grounded fallback" in caplog.text
    assert "stage=first_try violations=" in caplog.text
    assert "stage=regenerated violations=" in caplog.text


def test_checker_rejects_wrong_lagna_sign_even_when_sign_exists_elsewhere():
    facts = [
        "F001 : Lagna is Scorpio",
        "F007 : Saturn in house 6 (Pisces), retrograde, nakshatra Revati",
    ]
    answer = "Lagna may suggest a tendency toward Aries themes [F007]."
    errors = validate_answer(answer, facts)
    assert any("Lagna is not in Aries" in error for error in errors)


def test_groq_request_uses_low_reasoning_and_larger_visible_output_budget():
    calls = {}
    script = {"secret-1": complete("A reflective tendency may be present [F001][M034].")}
    answer = generate_answer("Question", ["F001 : Lagna is Scorpio"], api_keys=make_keys()[:1],
                             client_factory=fake_factory(script, calls), stream=False, gemini_api_key="")
    assert answer.succeeded
    request = calls["secret-1"][0]
    assert request["reasoning_effort"] == "low"
    assert request["max_completion_tokens"] >= 4096


def test_rejected_groq_answer_after_regeneration_hands_off_to_gemini(caplog):
    from api.app.llm.test_gemini import FakeGeminiClient, stream

    facts = ["F001 : Lagna is Scorpio", "F005 : Jupiter in house 10 (Leo), direct, nakshatra Magha"]
    invalid_one = "Jupiter may be in house 8 [F005]."
    invalid_two = "Jupiter may be in Aries [F005]."
    groq_calls = {}
    groq_script = {"secret-1": _scripted(complete(invalid_one), complete(invalid_two))}
    gemini = FakeGeminiClient([stream("Jupiter may support learning and perspective [F005][M017].")])
    with caplog.at_level(logging.WARNING):
        answer = generate_answer("What does Jupiter suggest?", facts, api_keys=make_keys()[:1],
                                 client_factory=fake_factory(groq_script, groq_calls), stream=False,
                                 gemini_api_key="fake-gemini", gemini_client_factory=lambda _: gemini)
    assert answer.provider == "gemini"
    assert answer.succeeded
    assert len(groq_calls["secret-1"]) == 2
    assert len(gemini.models.calls) == 1
    assert f"raw_answer={invalid_one!r}" in caplog.text
    assert f"raw_answer={invalid_two!r}" in caplog.text
