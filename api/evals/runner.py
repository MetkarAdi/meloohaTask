"""Live Groq-answer/Gemini-judge evaluation runner."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Sequence

from app.llm.groq import LLMAnswer, configured_keys, generate_answer
from app.llm.routing import route_question
from app.llm.validation import CITATION_RE, CERTAINTY_RE, check_answer

GEMMA_FALLBACK_MODEL = "gemma-4-26b-a4b-it"
JUDGE_PROMPT = (
    "Rate this astrology answer for a beginner, using only the supplied facts. "
    "Return JSON only with integer scores 1-5 for groundedness, specificity, "
    "plain_english_clarity, tone. 1=poor, 5=excellent. No other text.\n"
    "Q:{question}\nFacts:{facts}\nAnswer:{answer}"
)


def _default_gemini_client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key)


def _quota_exhausted(error: Exception) -> bool:
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    message = " ".join(str(value or "") for value in (
        getattr(error, "message", ""), getattr(error, "details", ""), error,
    )).casefold()
    compact = re.sub(r"[^a-z0-9]+", "", message)
    quota_words = ("per day", "daily", "requests_per_day", "requests per day", "rpd", "daily quota")
    daily_metric = any(word in compact for word in ("perday", "daily", "requestsperday", "requestpermodelperday"))
    return str(status) in {"429", "RESOURCE_EXHAUSTED"} and (daily_metric or any(word in message for word in quota_words))


def _judge_usage(response: Any, prompt: str, answer: str) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", None) if usage else None
    output_tokens = getattr(usage, "candidates_token_count", None) if usage else None
    return (
        int(input_tokens) if input_tokens is not None else max(1, (len(prompt) + 3) // 4),
        int(output_tokens) if output_tokens is not None else max(1, (len(answer) + 3) // 4),
    )


def _parse_scores(text: str) -> dict[str, int]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    data = json.loads(cleaned)
    fields = ("groundedness", "specificity", "plain_english_clarity", "tone")
    result: dict[str, int] = {}
    for field in fields:
        score = data[field]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 1 <= score <= 5:
            raise ValueError(f"invalid judge score: {field}")
        result[field] = int(score)
    return result


@dataclass
class JudgeResult:
    model: str
    scores: dict[str, int] | None
    prompt_tokens: int
    completion_tokens: int
    error: str | None = None


class GeminiJudge:
    """Gemini judge that latches to Gemma if Gemini's daily quota is exhausted."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 gemma_model: str = GEMMA_FALLBACK_MODEL, client_factory: Callable[[str], Any] | None = None):
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = (model if model is not None else os.getenv("GEMINI_MODEL", "")).strip()
        self.gemma_model = gemma_model
        self.client_factory = client_factory or _default_gemini_client
        self.use_gemma = False

    def __call__(self, question: str, facts: Sequence[str], answer: str) -> JudgeResult:
        if not self.api_key:
            return JudgeResult(self.gemma_model if self.use_gemma else self.model, None, 0, 0, "GEMINI_API_KEY is not set")
        if not self.model:
            return JudgeResult("", None, 0, 0, "GEMINI_MODEL is not set")
        prompt = JUDGE_PROMPT.format(question=question, facts=json.dumps(list(facts), separators=(",", ":")), answer=answer)
        models = [self.gemma_model] if self.use_gemma else [self.model]
        for model in models:
            client = None
            try:
                client = self.client_factory(self.api_key)
                from google.genai import types

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0, max_output_tokens=180),
                )
                text = (getattr(response, "text", None) or "").strip()
                scores = _parse_scores(text)
                input_tokens, output_tokens = _judge_usage(response, prompt, text)
                return JudgeResult(model, scores, input_tokens, output_tokens)
            except Exception as error:
                if model == self.model and not self.use_gemma and _quota_exhausted(error):
                    self.use_gemma = True
                    # Switch this question and all remaining eval questions to Gemma.
                    return self._judge_with_gemma(prompt)
                return JudgeResult(model, None, 0, 0, type(error).__name__)
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
        return JudgeResult(self.gemma_model, None, 0, 0, "judge unavailable")

    def _judge_with_gemma(self, prompt: str) -> JudgeResult:
        client = None
        try:
            from google.genai import types

            client = self.client_factory(self.api_key)
            response = client.models.generate_content(
                model=self.gemma_model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=180),
            )
            text = (getattr(response, "text", None) or "").strip()
            scores = _parse_scores(text)
            input_tokens, output_tokens = _judge_usage(response, prompt, text)
            return JudgeResult(self.gemma_model, scores, input_tokens, output_tokens)
        except Exception as error:
            return JudgeResult(self.gemma_model, None, 0, 0, type(error).__name__)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _judge_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    # Google's published Gemini API price sheet lists Gemma 4 as free-tier free,
    # with no paid token rate. The main Gemini model uses the shared rate table.
    if model.startswith("gemma-4-"):
        return Decimal("0")
    from app.llm.groq import _estimate_cost

    return _estimate_cost(model, prompt_tokens, completion_tokens)


def evaluate_cases(cases: Sequence[tuple[Any, str, str]], *, answer_generator: Callable[..., LLMAnswer] = generate_answer,
                   judge: Callable[[str, Sequence[str], str], JudgeResult] | None = None) -> list[dict[str, Any]]:
    judge = judge or GeminiJudge()
    records: list[dict[str, Any]] = []
    for index, (chart, topic, question) in enumerate(cases, start=1):
        facts = route_question(question, chart.facts)
        started = time.perf_counter()
        # Explicit empty Gemini key prevents the answer generator from using Gemini to write.
        result = answer_generator(question, facts, stream=False, gemini_api_key="")
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        hard_issues, soft_warnings = check_answer(result.answer, facts)
        valid_ids = {match.group(1).upper() for fact in facts if (match := re.match(r"\s*([FM]\d{3})\s*:", fact, re.I))}
        cited = {token.upper() for token in CITATION_RE.findall(result.answer)} & valid_ids
        fallback_template = (
            result.provider == "fallback"
            or "tendency-based point for reflection" in result.answer.casefold()
        )
        contains_banned = bool(CERTAINTY_RE.search(result.answer))
        judged = judge(question, facts, result.answer)
        writer_cost = result.estimated_cost_usd
        # Gemini's paid list-price estimate is available for the configured flash-lite model.
        judge_cost = _judge_cost(judged.model, judged.prompt_tokens, judged.completion_tokens) if judged.prompt_tokens or judged.completion_tokens else None
        combined_cost = writer_cost + judge_cost if writer_cost is not None and judge_cost is not None else None
        records.append({
            "index": index,
            "chart": chart.chart_id,
            "topic": topic,
            "question": question,
            "answer": result.answer,
            "writer_provider": result.provider,
            "writer_model": result.model,
            "generation_stage": result.validation_stage,
            "checker_passed": not hard_issues,
            "checker_violations": hard_issues,
            "soft_warnings": soft_warnings,
            "citations_present": bool(cited),
            "citation_ids": sorted(cited),
            "banned_phrases_present": contains_banned,
            "fallback_template_used": fallback_template,
            "generation_ms": duration_ms,
            "writer_tokens": result.total_tokens,
            "writer_cost_usd": _decimal_text(writer_cost),
            "judge_model": judged.model,
            "judge_scores": judged.scores,
            "judge_error": judged.error,
            "judge_tokens": judged.prompt_tokens + judged.completion_tokens,
            "judge_cost_usd": _decimal_text(judge_cost),
            "total_tokens": result.total_tokens + judged.prompt_tokens + judged.completion_tokens,
            "total_cost_usd": _decimal_text(combined_cost),
        })
    return records


def _mean(records: Sequence[dict[str, Any]], key: str) -> float | None:
    values = [record["judge_scores"][key] for record in records if record["judge_scores"] is not None]
    return sum(values) / len(values) if values else None


def render_report(records: Sequence[dict[str, Any]]) -> str:
    score_keys = ("groundedness", "specificity", "plain_english_clarity", "tone")
    score_summary = " | ".join(f"{key.replace('_', ' ').title()}: {_mean(records, key):.2f}/5" if _mean(records, key) is not None else f"{key.replace('_', ' ').title()}: n/a" for key in score_keys)
    passed = sum(record["checker_passed"] for record in records)
    cited = sum(record["citations_present"] for record in records)
    banned = sum(record["banned_phrases_present"] for record in records)
    fallback = sum(record["fallback_template_used"] for record in records)
    judge_ok = sum(record["judge_scores"] is not None for record in records)
    costs = [Decimal(record["total_cost_usd"]) for record in records if record["total_cost_usd"] is not None]
    average_cost = sum(costs, Decimal("0")) / len(costs) if costs else None
    lines = [
        "# Answer quality evaluation",
        "",
        f"- Evaluated answers: **{len(records)}** across three synthetic charts.",
        f"- Code checker passed: **{passed}/{len(records)}**; citations present: **{cited}/{len(records)}**; banned language: **{banned}/{len(records)}**; grounded fallback used: **{fallback}/{len(records)}**.",
        f"- Gemini/Gemma judge returned scores: **{judge_ok}/{len(records)}**.",
        f"- Average judge scores (1–5): {score_summary}.",
        f"- Average combined listed-price estimate: **${average_cost:.8f} per answer**." if average_cost is not None else "- Average combined listed-price estimate: **not available for all selected models**.",
        "- Costs use token-based published-rate estimates where available; actual free-tier billing is $0 (subject to quota). Missing provider usage or unpriced models are shown as n/a.",
        "",
        "## Five worst answers",
        "",
    ]
    def quality(record: dict[str, Any]) -> float:
        scores = record["judge_scores"] or {}
        return sum(scores.get(key, 0) for key in score_keys) / len(score_keys)
    worst = sorted(records, key=lambda item: (item["judge_scores"] is not None, quality(item), item["checker_passed"]))[:5]
    for record in worst:
        lines.extend([
            f"### #{record['index']} · {record['chart']} · {record['topic']}",
            "",
            f"**Question:** {record['question']}",
            "",
            f"**Answer:** {record['answer']}",
            "",
            f"**Judge:** {record['judge_scores'] or 'unavailable'} using `{record['judge_model'] or 'unset'}`; "
            f"**code:** checker={'pass' if record['checker_passed'] else 'fail'}, citations={'yes' if record['citations_present'] else 'no'}, "
            f"banned={'yes' if record['banned_phrases_present'] else 'no'}, fallback={'yes' if record['fallback_template_used'] else 'no'}, "
            f"time={record['generation_ms']} ms; tokens={record['total_tokens']}; cost=${record['total_cost_usd'] or 'n/a'}.",
        ])
        if record["checker_violations"]:
            lines.extend(["", "**Checker violations:** " + "; ".join(record["checker_violations"])])
        lines.append("")
    lines.extend(["## Per-answer results", "", "| # | Chart | Topic | Code checks | Judge scores (G/S/C/T) | Writer | Judge | Time ms | Tokens W/J | Cost USD |", "|---:|---|---|---|---|---|---|---:|---:|---:|"])
    for record in records:
        checks = "/".join(("pass" if record["checker_passed"] else "FAIL", "cite" if record["citations_present"] else "NO-CITE", "clean" if not record["banned_phrases_present"] else "BANNED", "no-fallback" if not record["fallback_template_used"] else "FALLBACK"))
        scores = record["judge_scores"]
        score_text = "/".join(str(scores[key]) for key in score_keys) if scores else "n/a"
        lines.append(f"| {record['index']} | {record['chart']} | {record['topic']} | {checks} | {score_text} | {record['writer_model']} | {record['judge_model'] or 'n/a'} | {record['generation_ms']:.2f} | {record['writer_tokens']}/{record['judge_tokens']} | {record['total_cost_usd'] or 'n/a'} |")
    return "\n".join(lines) + "\n"


def run(*, smoke: bool = False, report_path: Path | None = None) -> list[dict[str, Any]]:
    from .fixtures import selected_cases

    if not configured_keys():
        raise RuntimeError("No Groq API key is available in the process environment; eval answers must be written by Groq.")
    if not os.getenv("GEMINI_API_KEY", "").strip():
        raise RuntimeError("GEMINI_API_KEY is required for the independent Gemini judge.")
    if not os.getenv("GEMINI_MODEL", "").strip():
        raise RuntimeError("GEMINI_MODEL is required to select the independent Gemini judge.")
    records = evaluate_cases(selected_cases(smoke=smoke))
    report = render_report(records)
    print(report)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"Saved report: {report_path}")
    return records
