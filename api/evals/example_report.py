"""Generate a tiny, offline example report using a mock provider and judge."""

import json
from decimal import Decimal
from pathlib import Path

from app.llm.groq import LLMAnswer
from .fixtures import selected_cases
from .runner import JudgeResult, _summary, _thresholds, evaluate_cases, render_report


def main() -> None:
    case = selected_cases(smoke=True)[0]
    fact = next(item for item in case.chart.facts if item.startswith("F001"))
    sign = fact.rsplit(" ", 1)[-1]
    answer = f"Your ascendant is {sign} [F001]. This is a chart starting point for reflection."

    def writer(_question, _facts, **_kwargs):
        return LLMAnswer(answer, "groq", "mock-groq-writer", "mock-key-slot", 24, 14, 38,
                         Decimal("0.000006"), True, True, "first_try")

    def judge(_question, _facts, _answer):
        return JudgeResult("mock-gemini-judge", {
            "relevance": 5, "clarity": 5, "completeness": 4, "consistency": 5,
            "grounding": 5, "certainty_avoidance": 5,
        }, 60, 20)

    records = evaluate_cases([case], answer_generator=writer, judge=judge, writer="groq")
    summary = _summary(records)
    thresholds = _thresholds(summary, min_factual=1, min_grounding=1, min_interpretation=3, strict_subjective=True)
    markdown = "_Example format only; values below use a mocked writer and judge._\n\n" + render_report(records, summary=summary, threshold_results=thresholds)
    output = {"schema_version": 2, "as_of": "2026-11-15T12:00:00+00:00", "summary": summary,
              "previous_run_delta": None,
              "thresholds": {name: {"passed": ok, "detail": detail} for name, (ok, detail) in thresholds.items()},
              "records": records}
    docs = Path(__file__).resolve().parents[2] / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "eval-report.example.md").write_text(markdown, encoding="utf-8")
    (docs / "eval-report.example.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
