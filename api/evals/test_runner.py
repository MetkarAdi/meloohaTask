from decimal import Decimal
from types import SimpleNamespace

from app.llm.groq import LLMAnswer
from evals.fixtures import CHARTS, selected_cases
from evals.runner import GeminiJudge, JudgeResult, evaluate_cases


def _answer(question, facts, **kwargs):
    return LLMAnswer(
        "Career themes may emphasize patient effort [M010][F006]. Jupiter in house 10 (Leo) may add a focus on visibility [F006][M017].",
        "groq", "openai/gpt-oss-20b", "GROQ_API_KEY", 40, 20, 60,
        Decimal("0.00001"), False, True, "first_try",
    )


def test_eval_fixtures_are_three_synthetic_charts_and_30_fixed_questions():
    assert len(CHARTS) == 3
    assert len(selected_cases()) == 90
    assert len(selected_cases(smoke=True)) == 5
    assert all("synthetic-" in chart.chart_id for chart in CHARTS)
    assert {topic for _, topic, _ in selected_cases(smoke=True)} == {"career", "relationships", "timing"}
    assert {chart.chart_id for chart, _, _ in selected_cases(smoke=True)} == {chart.chart_id for chart in CHARTS}


def test_eval_records_checker_citations_fallback_timing_and_tokens():
    result = evaluate_cases(selected_cases(smoke=True)[:1], answer_generator=_answer,
                            judge=lambda q, f, a: JudgeResult("test-gemini", {
                                "groundedness": 5, "specificity": 4,
                                "plain_english_clarity": 4, "tone": 5,
                            }, 30, 10))
    record = result[0]
    assert record["checker_passed"] is True
    assert record["citations_present"] is True
    assert record["banned_phrases_present"] is False
    assert record["fallback_template_used"] is False
    assert record["generation_ms"] >= 0
    assert record["writer_tokens"] == 60
    assert record["total_tokens"] == 100
    assert record["judge_model"] != record["writer_model"]


def test_gemini_daily_quota_switches_current_and_remaining_judges_to_gemma():
    class QuotaError(Exception):
        status_code = 429
        message = "Requests per day quota exceeded"

    calls = []

    class FakeModels:
        def __init__(self, fail):
            self.fail = fail

        def generate_content(self, **kwargs):
            calls.append(kwargs["model"])
            if self.fail:
                raise QuotaError()
            return SimpleNamespace(
                text='{"groundedness":5,"specificity":4,"plain_english_clarity":5,"tone":4}',
                usage_metadata=SimpleNamespace(prompt_token_count=20, candidates_token_count=12),
            )

    def client_factory(_key):
        fail = len(calls) == 0
        return SimpleNamespace(models=FakeModels(fail), close=lambda: None)

    judge = GeminiJudge(api_key="fake", model="configured-gemini-model", client_factory=client_factory)
    first = judge("Q", ["F001 : Lagna is Aries"], "A")
    second = judge("Q2", ["F001 : Lagna is Aries"], "A2")
    assert first.model == "gemma-4-26b-a4b-it"
    assert second.model == "gemma-4-26b-a4b-it"
    assert first.scores["groundedness"] == 5
    assert calls == ["configured-gemini-model", "gemma-4-26b-a4b-it", "gemma-4-26b-a4b-it"]
