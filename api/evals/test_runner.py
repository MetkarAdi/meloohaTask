from decimal import Decimal
from types import SimpleNamespace

from app.llm.groq import LLMAnswer
from evals.fixtures import CHARTS, selected_cases, CASES
from evals.runner import GeminiJudge, JudgeResult, evaluate_cases, _parse_scores, _summary, _thresholds, _previous_diff
from evals.validator import validate_eval_answer
from app.llm.routing import route_question


def _answer(question, facts, **kwargs):
    return LLMAnswer("Your ascendant is Virgo, which can describe a grounded approach [F001].", "groq", "openai/gpt-oss-20b", "GROQ_API_KEY", 40, 20, 60, Decimal("0.00001"), False, True, "first_try")


def _scores():
    return {"relevance": 5, "clarity": 4, "completeness": 4, "consistency": 5, "grounding": 5, "certainty_avoidance": 5}


def test_eval_fixtures_are_engine_verified_synthetic_charts_and_broad_dataset():
    assert len(CHARTS) == 3
    assert len(CASES) == 75
    assert len(selected_cases(smoke=True)) == 6
    assert all(item.chart_id.startswith("synthetic-") for item in CHARTS)
    assert {case.category for case in CASES} == {"basic", "placement", "lordship", "divisional", "dasha", "interpretation", "unanswerable"}
    assert {case.chart_id for case in CHARTS} == {"synthetic-a", "synthetic-b", "synthetic-c"}
    assert all(case.chart.as_of.isoformat() == "2026-11-15T12:00:00+00:00" for case in CASES)
    assert all(len(case.chart.result.planets) == 9 for case in CASES[:1])


def test_eval_records_deterministic_checks_latency_tokens_cost_and_six_judge_dimensions():
    case = selected_cases(smoke=True)[0]
    facts = route_question(case.question, case.chart.facts)
    answer = f"Your ascendant is {case.chart.result.lagna_sign}, a chart fact [F001]."
    def generate(_question, _facts, **_kwargs):
        return LLMAnswer(answer, "groq", "openai/gpt-oss-20b", "GROQ_API_KEY", 40, 20, 60, Decimal("0.00001"), False, True, "first_try")
    result = evaluate_cases([case], answer_generator=generate, judge=lambda _q, _f, _a: JudgeResult("test-gemini", _scores(), 30, 10), writer="groq")[0]
    assert result["factual_pass"] is True
    assert result["grounding_pass"] is True
    assert result["generation_ms"] >= 0
    assert result["writer_tokens"] == 60
    assert result["total_tokens"] == 100
    assert result["judge_model"] != result["writer_model"]
    assert set(result["judge_scores"]) == {"relevance", "clarity", "completeness", "consistency", "grounding", "certainty_avoidance"}


def test_deterministic_validator_rejects_wrong_house_and_d9_d1_swap():
    saturn_case = next(case for case in CASES if case.chart.chart_id == "synthetic-a" and case.category == "placement" and case.case_id.endswith("second-house-occupants"))
    saturn = next(p for p in saturn_case.chart.result.planets if p.name == "Saturn")
    wrong_house = saturn.house % 12 + 1
    wrong_facts = route_question("Where is Saturn placed in D1?", saturn_case.chart.facts)
    from dataclasses import replace
    case = replace(saturn_case, question="Where is Saturn placed in D1?", required_terms=("Saturn", saturn.sign, str(saturn.house), "D1"))
    result = validate_eval_answer(f"In D1, Saturn is in house {wrong_house} ({saturn.sign}).", wrong_facts, case)
    assert not result.passed
    assert result.violations

    d9_case = next(case for case in CASES if case.case_id == "synthetic-a-jupiter-d9")
    jupiter = next(p for p in d9_case.chart.result.planets if p.name == "Jupiter")
    facts = route_question(d9_case.question, d9_case.chart.facts)
    swapped = validate_eval_answer(f"In D9 Jupiter is in house {jupiter.house} ({jupiter.sign}).", facts, d9_case)
    assert not swapped.passed
    assert any("D9" in violation for violation in swapped.violations)


def test_unanswerable_and_unsupported_placements_require_a_clear_acknowledgment():
    case = next(case for case in CASES if case.case_id == "synthetic-a-uranus")
    facts = route_question(case.question, case.chart.facts)
    assert not validate_eval_answer("Uranus is in the tenth house.", facts, case).passed
    safe = validate_eval_answer("Uranus is not included in the supplied chart facts, so its placement is not available.", facts, case)
    assert safe.passed


def test_router_supplies_house_lords_and_divisional_context_from_engine_facts():
    chart = CHARTS[1]
    lord_case = next(case for case in CASES if case.chart.chart_id == chart.chart_id and case.case_id.endswith("tenth-lord-placement"))
    lord_name = lord_case.required_terms[0]
    lord = next(p for p in chart.result.planets if p.name == lord_name)
    facts = route_question(lord_case.question, chart.facts)
    assert any("D1 house 10 sign is" in fact and f"ruler is {lord_name}" in fact for fact in facts)
    assert any(fact.startswith("F") and f"{lord_name} in house {lord.house}" in fact for fact in facts)
    d9 = next(case for case in CASES if case.chart.chart_id == chart.chart_id and case.case_id.endswith("jupiter-d9"))
    assert any("D9 Jupiter in house" in fact for fact in route_question(d9.question, chart.facts))


def test_judge_scores_are_strict_json_and_daily_quota_switches_to_gemma():
    serialized = '{"relevance":5,"clarity":4,"completeness":4,"consistency":5,"grounding":5,"certainty_avoidance":5}'
    assert _parse_scores(serialized) == _scores()
    try:
        _parse_scores('{"relevance":6}')
    except (KeyError, ValueError):
        pass
    else:
        raise AssertionError("invalid judge schema must be rejected")

    class QuotaError(Exception):
        status_code = 429
        message = "Requests per day quota exceeded"
    calls = []
    class FakeModels:
        def __init__(self, fail): self.fail = fail
        def generate_content(self, **kwargs):
            calls.append(kwargs["model"])
            if self.fail: raise QuotaError()
            return SimpleNamespace(text=serialized, usage_metadata=SimpleNamespace(prompt_token_count=20, candidates_token_count=12))
    def factory(_key):
        fail = len(calls) == 0
        return SimpleNamespace(models=FakeModels(fail), close=lambda: None)
    judge = GeminiJudge(api_key="fake", model="configured-gemini-model", client_factory=factory)
    assert judge("Q", ["F001 : Lagna is Aries"], "A").model == "gemma-4-26b-a4b-it"
    assert judge("Q2", ["F001 : Lagna is Aries"], "A2").model == "gemma-4-26b-a4b-it"
    assert calls == ["configured-gemini-model", "gemma-4-26b-a4b-it", "gemma-4-26b-a4b-it"]


def test_groq_judge_validates_json_and_usage_counts():
    import json
    from app.llm.groq import APIKey
    from evals.runner import GroqJudge
    class Client:
        def __init__(self):
            output = "```json\n" + json.dumps(_scores()) + "\n```"
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=output))],
                usage=SimpleNamespace(prompt_tokens=14, completion_tokens=9))))
        def close(self):
            pass
    judge = GroqJudge(model="judge-model", keys=[APIKey("GROQ_API_KEY", "fake")], client_factory=lambda _key: Client())
    result = judge("Q", ["F001 : Lagna is Aries"], "Answer")
    assert result.model == "judge-model"
    assert result.scores == _scores()
    assert (result.prompt_tokens, result.completion_tokens) == (14, 9)


def test_thresholds_gate_deterministic_failures_but_subjective_scores_are_advisory_by_default():
    case = selected_cases(smoke=True)[0]
    rows = evaluate_cases([case], answer_generator=lambda *_args, **_kwargs: LLMAnswer(
        f"Your ascendant is {case.chart.result.lagna_sign} [F001].", "gemini", "gemini-test", "", 2, 3, 5,
        Decimal("0.00001"), False, True, "first_try"), judge=lambda *_args: JudgeResult("judge", _scores() | {"relevance": 2}, 10, 5))
    summary = _summary(rows)
    advisory = _thresholds(summary, min_factual=1.0, min_grounding=1.0, min_interpretation=4.9, strict_subjective=False)
    assert advisory["gemini interpretation quality"][0] is True
    strict = _thresholds(summary, min_factual=1.0, min_grounding=1.0, min_interpretation=4.9, strict_subjective=True)
    assert strict["gemini interpretation quality"][0] is False
    assert _previous_diff(summary, {"summary": {"by_provider": {"gemini": summary["by_provider"]["gemini"]}}})["gemini"]["factual_accuracy"] == 0

    invalid = [dict(rows[0], factual_pass=False, critical_factual_failure=True, grounding_pass=False)]
    failed = _thresholds(_summary(invalid), min_factual=0.0, min_grounding=0.0, min_interpretation=1.0, strict_subjective=False)
    assert failed["gemini critical factual checks"][0] is False
