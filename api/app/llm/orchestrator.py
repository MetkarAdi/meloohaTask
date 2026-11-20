from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from decimal import Decimal
from typing import Any, Callable, Sequence

from .groq import FALLBACK_MESSAGE, APIKey, LLMAnswer, generate_groq_answer
from .routing import route_question
from .language import localized_unavailable

LOGGER = logging.getLogger("melooha.llm.orchestrator")


def _combine_usage(first: LLMAnswer, second: LLMAnswer) -> LLMAnswer:
    cost = (
        first.estimated_cost_usd + second.estimated_cost_usd
        if first.estimated_cost_usd is not None and second.estimated_cost_usd is not None
        else None
    )
    return replace(
        second,
        prompt_tokens=first.prompt_tokens + second.prompt_tokens,
        completion_tokens=first.completion_tokens + second.completion_tokens,
        total_tokens=first.total_tokens + second.total_tokens,
        estimated_cost_usd=cost,
        usage_is_estimated=first.usage_is_estimated or second.usage_is_estimated,
    )


def generate_answer(
    question: str,
    facts: Sequence[str],
    *,
    api_keys: Sequence[APIKey] | None = None,
    model: str | None = None,
    stream: bool = True,
    client_factory: Callable[[str], Any] | None = None,
    gemini_api_key: str | None = None,
    gemini_model: str | None = None,
    gemini_client_factory: Callable[[str], Any] | None = None,
    on_section: Callable[[str, str], None] | None = None,
    on_reset: Callable[[], None] | None = None,
) -> LLMAnswer:
    """Generate with Gemini first, then rotate through configured Groq keys."""
    if not question.strip() or not facts:
        LOGGER.warning("Answer generation skipped reason=%s", "missing_question" if not question.strip() else "missing_chart_facts")
        return LLMAnswer(FALLBACK_MESSAGE, "none", "unavailable", None, 0, 0, 0, Decimal("0"), False, False,
                         "provider_failed", "missing_question_or_chart_facts")

    if not any(re.match(r"^\s*M\d{3}\s*:", fact, re.I) for fact in facts):
        facts = route_question(question, facts)

    gemini_key = (gemini_api_key if gemini_api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
    gemini_result: LLMAnswer | None = None
    if gemini_key:
        from .gemini import generate_gemini_answer

        selected_gemini_model = (gemini_model or os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite").strip()
        gemini_result = generate_gemini_answer(
            question,
            facts,
            api_key=gemini_key,
            model=selected_gemini_model,
            client_factory=gemini_client_factory,
            stream=stream,
            on_section=on_section,
            on_reset=on_reset,
        )
        if gemini_result.succeeded:
            return gemini_result
        LOGGER.warning(
            "Primary provider failed provider=gemini model=%s category=%s; trying secondary provider",
            selected_gemini_model,
            gemini_result.failure_reason or gemini_result.validation_stage,
        )
    else:
        LOGGER.warning("Primary provider unavailable provider=gemini reason=missing_api_key; trying secondary provider")

    if gemini_result is not None and on_reset:
        on_reset()
    groq_result = generate_groq_answer(
        question,
        facts,
        api_keys=api_keys,
        model=model,
        stream=stream,
        client_factory=client_factory,
        on_section=on_section,
        on_reset=on_reset,
    )
    if groq_result.succeeded:
        return _combine_usage(gemini_result, groq_result) if gemini_result is not None else groq_result

    gemini_failure = gemini_result.failure_reason if gemini_result else "missing_api_key"
    LOGGER.error(
        "All answer providers failed; returning friendly failure gemini_failure=%s groq_failure=%s",
        gemini_failure,
        groq_result.failure_reason or "provider_failed",
    )
    prompt_tokens = groq_result.prompt_tokens + (gemini_result.prompt_tokens if gemini_result else 0)
    completion_tokens = groq_result.completion_tokens + (gemini_result.completion_tokens if gemini_result else 0)
    costs = [result.estimated_cost_usd for result in (gemini_result, groq_result) if result is not None]
    estimated_cost = sum(costs, Decimal("0")) if len(costs) == 2 and all(cost is not None for cost in costs) else None
    return LLMAnswer(
        answer=localized_unavailable(question),
        provider="none",
        model="provider-failover-exhausted",
        api_key_slot=None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        estimated_cost_usd=estimated_cost,
        usage_is_estimated=groq_result.usage_is_estimated or bool(gemini_result and gemini_result.usage_is_estimated),
        succeeded=False,
        validation_stage="provider_failed",
        failure_reason="provider_failover_exhausted",
    )
