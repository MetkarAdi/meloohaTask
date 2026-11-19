"""Paired provider evaluation with deterministic chart checks and independent judges."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Sequence

from app.llm.groq import LLMAnswer, configured_keys, generate_answer
from app.llm.routing import route_question
from app.llm.validation import CITATION_RE, CERTAINTY_RE
from .fixtures import EvalCase, selected_cases
from .validator import validate_eval_answer

GEMMA_FALLBACK_MODEL = "gemma-4-26b-a4b-it"
SCORE_FIELDS = ("relevance", "clarity", "completeness", "consistency", "grounding", "certainty_avoidance")
JUDGE_PROMPT = """Evaluate a Vedic astrology answer for a beginner. Use only the supplied chart context. Score each dimension from 1 (poor) to 5 (excellent): relevance answers the question; clarity uses plain English; completeness covers requested parts; consistency does not mix D1/D9/D10 or contradict itself; grounding uses only supplied chart data and separates data from interpretation; certainty_avoidance avoids unsupported promises and confident predictions (5 means appropriately cautious). Do not reward confidence. Return one JSON object with exactly these integer keys: relevance, clarity, completeness, consistency, grounding, certainty_avoidance. No prose.
Q:{question}
Context:{facts}
Answer:{answer}"""


def _default_gemini_client(api_key: str):
    from google import genai
    return genai.Client(api_key=api_key)


def _quota_exhausted(error: Exception) -> bool:
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    message = " ".join(str(value or "") for value in (getattr(error, "message", ""), getattr(error, "details", ""), error)).casefold()
    compact = re.sub(r"[^a-z0-9]+", "", message)
    daily_metric = any(word in compact for word in ("perday", "daily", "requestsperday", "requestpermodelperday"))
    return str(status) in {"429", "RESOURCE_EXHAUSTED"} and (daily_metric or any(word in message for word in ("per day", "daily quota", "requests per day", "rpd")))


def _usage(response: Any, prompt: str, output: str) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", None) if usage else None
    output_tokens = getattr(usage, "candidates_token_count", None) if usage else None
    return (int(input_tokens) if input_tokens is not None else max(1, (len(prompt) + 3) // 4),
            int(output_tokens) if output_tokens is not None else max(1, (len(output) + 3) // 4))


def _parse_scores(text: str) -> dict[str, int]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    data = json.loads(cleaned)
    if not isinstance(data, dict) or set(data) != set(SCORE_FIELDS):
        raise ValueError("judge JSON must contain exactly the six required score fields")
    scores = {}
    for field in SCORE_FIELDS:
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"invalid judge score: {field}")
        scores[field] = value
    return scores


@dataclass
class JudgeResult:
    model: str
    scores: dict[str, int] | None
    prompt_tokens: int
    completion_tokens: int
    error: str | None = None


class GeminiJudge:
    """Gemini judge; switches to the configured Gemma fallback after daily quota exhaustion."""
    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 gemma_model: str = GEMMA_FALLBACK_MODEL, client_factory: Callable[[str], Any] | None = None):
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = (model if model is not None else os.getenv("GEMINI_MODEL", "")).strip()
        self.gemma_model = gemma_model
        self.client_factory = client_factory or _default_gemini_client
        self.use_gemma = False

    def __call__(self, question: str, facts: Sequence[str], answer: str) -> JudgeResult:
        if not self.api_key or not self.model:
            return JudgeResult(self.model or self.gemma_model, None, 0, 0, "Gemini judge is not configured")
        prompt = JUDGE_PROMPT.format(question=question, facts=json.dumps(list(facts), separators=(",", ":")), answer=answer)
        model = self.gemma_model if self.use_gemma else self.model
        try:
            result = self._request(model, prompt)
            return result
        except Exception as error:
            if model == self.model and _quota_exhausted(error):
                self.use_gemma = True
                try:
                    return self._request(self.gemma_model, prompt)
                except Exception as gemma_error:
                    return JudgeResult(self.gemma_model, None, 0, 0, type(gemma_error).__name__)
            return JudgeResult(model, None, 0, 0, type(error).__name__)

    def _request(self, model: str, prompt: str) -> JudgeResult:
        client = None
        try:
            from google.genai import types
            client = self.client_factory(self.api_key)
            response = client.models.generate_content(model=model, contents=prompt,
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=240))
            output = (getattr(response, "text", None) or "").strip()
            if not output:
                raise ValueError("empty judge output")
            input_tokens, output_tokens = _usage(response, prompt, output)
            return JudgeResult(model, _parse_scores(output), input_tokens, output_tokens)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()


class GroqJudge:
    """Structured JSON judge used for Gemini-written answers."""
    def __init__(self, *, model: str | None = None, keys=None, client_factory=None):
        from groq import Groq
        self.model = (model or os.getenv("EVAL_GROQ_JUDGE_MODEL") or os.getenv("GROQ_MODEL") or "openai/gpt-oss-20b").strip()
        self.keys = list(keys if keys is not None else configured_keys())
        self.client_factory = client_factory or (lambda secret: Groq(api_key=secret, max_retries=0))

    def __call__(self, question: str, facts: Sequence[str], answer: str) -> JudgeResult:
        prompt = JUDGE_PROMPT.format(question=question, facts=json.dumps(list(facts), separators=(",", ":")), answer=answer)
        from groq import BadRequestError
        for key in self.keys:
            client = None
            try:
                client = self.client_factory(key.secret)
                result = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": "Return only valid JSON matching the requested score fields."}, {"role": "user", "content": prompt}],
                    temperature=0,
                    max_completion_tokens=240,
                    stream=False,
                )
                choices = getattr(result, "choices", []) or []
                output = (getattr(getattr(choices[0], "message", None), "content", None) or "").strip() if choices else ""
                if not output:
                    raise ValueError("empty judge output")
                usage = getattr(result, "usage", None)
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or max(1, (len(prompt) + 3) // 4))
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or max(1, (len(output) + 3) // 4))
                return JudgeResult(self.model, _parse_scores(output), prompt_tokens, completion_tokens)
            except BadRequestError as error:
                return JudgeResult(self.model, None, 0, 0, type(error).__name__)
            except Exception as error:
                continue
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
        return JudgeResult(self.model, None, 0, 0, "judge_unavailable_or_invalid_json")


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _judge_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    if not model or model.startswith("gemma-4-"):
        return Decimal("0") if model.startswith("gemma-4-") else None
    from app.llm.groq import _estimate_cost
    if model.startswith("openai/") or "/" in model:
        return _estimate_cost(model, prompt_tokens, completion_tokens)
    # Gemini 3.5 Flash Lite estimate; actual free-tier charges remain quota-dependent.
    return (Decimal(prompt_tokens) * Decimal("0.30") + Decimal(completion_tokens) * Decimal("2.50")) / Decimal(1_000_000)


def _case_facts(case: EvalCase) -> list[str]:
    return route_question(case.question, case.chart.facts)


def evaluate_cases(cases: Sequence[EvalCase], *, answer_generator: Callable[..., LLMAnswer] = generate_answer,
                   judge: Callable[[str, Sequence[str], str], JudgeResult] | None = None,
                   writer: str | None = None) -> list[dict[str, Any]]:
    records = []
    for index, case in enumerate(cases, start=1):
        facts = _case_facts(case)
        started = time.perf_counter()
        result = answer_generator(case.question, facts, stream=False, gemini_api_key="")
        generation_ms = round((time.perf_counter() - started) * 1000, 2)
        deterministic = validate_eval_answer(result.answer, facts, case)
        cited = {token.upper() for token in CITATION_RE.findall(result.answer)}
        valid_ids = {match.group(1).upper() for fact in facts if (match := re.match(r"\s*([FM]\d{3})\s*:", fact, re.I))}
        fallback = result.provider in {"none", "fallback"} or "tendency-based point for reflection" in result.answer.casefold()
        banned = bool(CERTAINTY_RE.search(result.answer))
        judged = judge(case.question, facts, result.answer) if judge else JudgeResult("not-run", None, 0, 0, "judge not configured")
        judge_cost = _judge_cost(judged.model, judged.prompt_tokens, judged.completion_tokens)
        combined_cost = result.estimated_cost_usd + judge_cost if result.estimated_cost_usd is not None and judge_cost is not None else None
        records.append({
            "case_id": case.case_id, "chart": case.chart.chart_id, "category": case.category,
            "question": case.question, "answer": result.answer, "writer_provider": writer or result.provider,
            "writer_model": result.model, "judge_model": judged.model, "judge_scores": judged.scores,
            "judge_error": judged.error, "generation_ms": generation_ms,
            "factual_pass": deterministic.passed, "grounding_pass": deterministic.grounding_passed,
            "critical_factual_failure": bool(deterministic.violations),
            "violations": list(deterministic.violations), "missing_expected": list(deterministic.missing_expected),
            "missing_acknowledgment": deterministic.missing_acknowledgment,
            "checker_passed": deterministic.grounding_passed, "fallback_template_used": fallback,
            "banned_phrases_present": banned, "citations_present": bool(cited & valid_ids),
            "citation_ids": sorted(cited & valid_ids), "writer_tokens": result.total_tokens,
            "writer_cost_usd": _decimal_text(result.estimated_cost_usd), "judge_tokens": judged.prompt_tokens + judged.completion_tokens,
            "judge_cost_usd": _decimal_text(judge_cost), "total_tokens": result.total_tokens + judged.prompt_tokens + judged.completion_tokens,
            "total_cost_usd": _decimal_text(combined_cost), "generation_stage": result.validation_stage,
        })
    return records


def _summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    providers = {}
    for provider in sorted({item["writer_provider"] for item in records}):
        rows = [item for item in records if item["writer_provider"] == provider]
        judged = [item for item in rows if item["judge_scores"]]
        scores = {key: mean(row["judge_scores"][key] for row in judged) if judged else None for key in SCORE_FIELDS}
        cost_values = [Decimal(row["total_cost_usd"]) for row in rows if row["total_cost_usd"] is not None]
        writer_costs = [Decimal(row["writer_cost_usd"]) for row in rows if row["writer_cost_usd"] is not None]
        providers[provider] = {
            "questions": len(rows), "factual_accuracy": sum(row["factual_pass"] for row in rows) / len(rows) if rows else 0,
            "grounding_rate": sum(row["grounding_pass"] for row in rows) / len(rows) if rows else 0,
            "critical_failures": sum(row["critical_factual_failure"] for row in rows),
            "average_generation_ms": mean(row["generation_ms"] for row in rows) if rows else 0,
            "average_writer_tokens": mean(row["writer_tokens"] for row in rows) if rows else 0,
            "average_total_tokens": mean(row["total_tokens"] for row in rows) if rows else 0,
            "average_writer_cost_usd": str(mean(writer_costs)) if writer_costs else None,
            "average_cost_per_answer_usd": str(mean(cost_values)) if cost_values else None,
            "average_judge_scores": scores,
            "interpretation_quality": mean([scores[key] for key in ("relevance", "completeness", "clarity") if scores[key] is not None]) if scores and any(scores[key] is not None for key in ("relevance", "completeness", "clarity")) else None,
        }
    return {"questions": len(records), "by_provider": providers}


def _previous_diff(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any] | None:
    if not previous:
        return None
    old = previous.get("summary", {}).get("by_provider", {})
    diff = {}
    for provider, metrics in current.get("by_provider", {}).items():
        if provider not in old:
            continue
        diff[provider] = {}
        for key in ("factual_accuracy", "grounding_rate", "average_generation_ms", "interpretation_quality"):
            before, after = old[provider].get(key), metrics.get(key)
            diff[provider][key] = round(after - before, 4) if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
    return diff


def render_report(records: Sequence[dict[str, Any]], *, summary=None, previous_diff=None, threshold_results=None) -> str:
    summary = summary or _summary(records)
    lines = ["# Astrology answer evaluation", "", f"- Questions evaluated: **{summary['questions']}** across three engine-verified synthetic charts.",
             "- Deterministic fact checks compare answers with the chart engine's D1/D9/D10, house-lord, nakshatra/pada and Vimshottari values. The LLM judge is supplementary.", "",
             "## Provider comparison", "", "| Writer | Factual accuracy | Grounding | Interpretation / 5 | Avg latency ms | Avg writer tokens | Avg cost / answer | Critical failures |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for provider, metrics in summary["by_provider"].items():
        score = metrics["interpretation_quality"]
        lines.append(f"| {provider} | {metrics['factual_accuracy']:.1%} | {metrics['grounding_rate']:.1%} | {score:.2f}" if score is not None else f"| {provider} | {metrics['factual_accuracy']:.1%} | {metrics['grounding_rate']:.1%} | n/a")
        lines[-1] += f" | {metrics['average_generation_ms']:.1f} | {metrics['average_writer_tokens']:.1f} | ${metrics['average_cost_per_answer_usd'] or 'n/a'} | {metrics['critical_failures']} |"
    lines.extend(["", "Judge dimensions are relevance, plain-English clarity, completeness, consistency, grounding and avoidance of unsupported certainty. A missing judge score is reported as unavailable and does not itself fail CI.", ""])
    if previous_diff is None:
        lines.extend(["## Previous run comparison", "", "No previous JSON report was supplied for comparison.", ""])
    else:
        lines.extend(["## Previous run comparison", "", "Delta is current minus previous run.", ""])
        for provider, delta in previous_diff.items():
            lines.append(f"- **{provider}:** " + ", ".join(f"{key} {value:+.4f}" if value is not None else f"{key} n/a" for key, value in delta.items()))
        lines.append("")
    lines.extend(["## Five worst answers", ""])
    def risk(row):
        scores = row["judge_scores"] or {}
        return (row["factual_pass"], row["grounding_pass"], mean(scores.values()) if scores else 0)
    for row in sorted(records, key=risk)[:5]:
        lines.extend([f"### {row['case_id']} · {row['writer_provider']}", "", f"**Question:** {row['question']}", "", f"**Answer:** {row['answer']}", "",
                      f"**Checks:** factual={'pass' if row['factual_pass'] else 'FAIL'}, grounded={'pass' if row['grounding_pass'] else 'FAIL'}, missing expected={row['missing_expected'] or 'none'}, judge={row['judge_scores'] or 'unavailable'}.", ""])
        if row["violations"]:
            lines.append("Violations: " + "; ".join(row["violations"]) + "\n")
    if threshold_results:
        lines.extend(["## Thresholds", ""])
        lines.extend(f"- {name}: {'PASS' if passed else 'FAIL'} ({detail})" for name, (passed, detail) in threshold_results.items())
        lines.append("")
    lines.extend(["## Per-answer details", "", "| Case | Writer | Category | Factual | Grounded | Judge avg | Latency ms | Writer tokens | Total cost USD |", "|---|---|---|---|---|---:|---:|---:|---:|"])
    for row in records:
        scores = row["judge_scores"]
        avg = mean(scores.values()) if scores else None
        lines.append(f"| {row['case_id']} | {row['writer_provider']} | {row['category']} | {'pass' if row['factual_pass'] else 'FAIL'} | {'pass' if row['grounding_pass'] else 'FAIL'} | {avg:.2f}" if avg is not None else f"| {row['case_id']} | {row['writer_provider']} | {row['category']} | {'pass' if row['factual_pass'] else 'FAIL'} | {'pass' if row['grounding_pass'] else 'FAIL'} | n/a")
        lines[-1] += f" | {row['generation_ms']:.1f} | {row['writer_tokens']} | {row['total_cost_usd'] or 'n/a'} |"
    return "\n".join(lines) + "\n"


def _thresholds(summary: dict[str, Any], *, min_factual: float, min_grounding: float, min_interpretation: float, strict_subjective: bool):
    results = {}
    for provider, metrics in summary["by_provider"].items():
        results[f"{provider} critical factual checks"] = (metrics["critical_failures"] == 0, f"{metrics['critical_failures']} critical violations")
        results[f"{provider} factual accuracy"] = (metrics["factual_accuracy"] >= min_factual, f"{metrics['factual_accuracy']:.1%} >= {min_factual:.1%}")
        results[f"{provider} grounding"] = (metrics["grounding_rate"] >= min_grounding, f"{metrics['grounding_rate']:.1%} >= {min_grounding:.1%}")
        score = metrics["interpretation_quality"]
        ok = score is not None and score >= min_interpretation
        results[f"{provider} interpretation quality"] = (ok if strict_subjective else True, f"{score:.2f} >= {min_interpretation:.2f}" if score is not None else "judge score unavailable; subjective gate is advisory")
    return results


def _writer(provider: str):
    def generate(question, facts, **kwargs):
        if provider == "gemini":
            return generate_answer(question, facts, stream=False, gemini_api_key=os.getenv("GEMINI_API_KEY", ""), gemini_model=os.getenv("GEMINI_MODEL"), api_keys=[])
        return generate_answer(question, facts, stream=False, gemini_api_key="", api_keys=configured_keys())
    return generate


def run(*, smoke: bool = False, report_path: Path | None = None, json_path: Path | None = None,
        provider: str = "both", previous_json: Path | None = None,
        min_factual: float | None = None, min_grounding: float | None = None,
        min_interpretation: float | None = None, strict_subjective: bool | None = None) -> list[dict[str, Any]]:
    cases = selected_cases(smoke=smoke)
    providers = ("gemini", "groq") if provider == "both" else (provider,)
    if provider not in {"both", "gemini", "groq"}:
        raise ValueError("provider must be both, gemini, or groq")
    if "gemini" in providers and not os.getenv("GEMINI_API_KEY", "").strip():
        raise RuntimeError("GEMINI_API_KEY is required for Gemini answer generation or judging.")
    if "groq" in providers and not configured_keys():
        raise RuntimeError("At least one Groq API key is required for Groq answer generation or judging.")
    rows = []
    for writer_provider in providers:
        judge = GroqJudge() if writer_provider == "gemini" else GeminiJudge()
        rows.extend(evaluate_cases(cases, answer_generator=_writer(writer_provider), judge=judge, writer=writer_provider))
    summary = _summary(rows)
    previous = None
    if previous_json and previous_json.exists():
        previous = json.loads(previous_json.read_text(encoding="utf-8"))
    diff = _previous_diff(summary, previous)
    env_float = lambda key, default: float(os.getenv(key, str(default)))
    min_factual = min_factual if min_factual is not None else env_float("EVAL_MIN_FACTUAL_ACCURACY", 0.70 if smoke else 0.85)
    min_grounding = min_grounding if min_grounding is not None else env_float("EVAL_MIN_GROUNDING_RATE", 0.90)
    min_interpretation = min_interpretation if min_interpretation is not None else env_float("EVAL_MIN_INTERPRETATION_QUALITY", 3.4)
    strict_subjective = strict_subjective if strict_subjective is not None else os.getenv("EVAL_STRICT_SUBJECTIVE", "0").casefold() in {"1", "true", "yes"}
    threshold_results = _thresholds(summary, min_factual=min_factual, min_grounding=min_grounding, min_interpretation=min_interpretation, strict_subjective=strict_subjective)
    markdown = render_report(rows, summary=summary, previous_diff=diff, threshold_results=threshold_results)
    output = {"schema_version": 2, "as_of": "2026-11-15T12:00:00+00:00", "summary": summary, "previous_run_delta": diff,
              "thresholds": {name: {"passed": ok, "detail": detail} for name, (ok, detail) in threshold_results.items()}, "records": rows}
    print(markdown)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown, encoding="utf-8")
        print(f"Saved Markdown report: {report_path}")
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Saved JSON report: {json_path}")
    if any(not passed for passed, _detail in threshold_results.values()):
        raise RuntimeError("Evaluation thresholds failed; inspect the generated report for details.")
    return rows
