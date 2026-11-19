from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Callable, Sequence

from .groq import (
    FALLBACK_MESSAGE,
    LLMAnswer,
    _approx_tokens,
    _estimate_cost,
    _messages,
    _read,
    _usage_counts,
)
from .validation import safe_fact_answer, validate_answer

LOGGER = logging.getLogger("melooha.llm.gemini")
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _default_client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key)


def _extract_stream(response: Any) -> tuple[str, Any]:
    parts: list[str] = []
    usage = None
    for chunk in response:
        usage = _read(chunk, "usage_metadata", usage)
        text = _read(chunk, "text")
        if text:
            parts.append(str(text))
    if usage is not None:
        usage = {
            "prompt_tokens": _read(usage, "prompt_token_count"),
            "completion_tokens": _read(usage, "candidates_token_count"),
        }
    return "".join(parts).strip(), usage


def generate_gemini_answer(
    question: str,
    facts: Sequence[str],
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    client_factory: Callable[[str], Any] | None = None,
    stream: bool = True,
) -> LLMAnswer:
    """Generate one Gemini fallback response and enforce the shared fact checker."""
    if not question.strip() or not facts:
        return LLMAnswer(FALLBACK_MESSAGE, "gemini", model, None, 0, 0, 0, Decimal("0"), False, False)

    from google.genai import types

    factory = client_factory or _default_client
    client = None
    started = time.monotonic()
    prompt_tokens = 0
    completion_tokens = 0
    cost_total: Decimal | None = Decimal("0")
    estimated_any = False
    messages = _messages(question, facts)
    # The SDK receives just the question and computed facts as input content.
    user_content = messages[1]["content"]
    system_instruction = messages[0]["content"]
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.4,
        max_output_tokens=4096,
    )

    def request(contents: str) -> tuple[str, Any]:
        response = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        )
        if stream:
            return _extract_stream(response)
        # The stream endpoint is used for both modes to keep provider handling uniform.
        return _extract_stream(response)

    def add_usage(usage: Any, prompt: str, text: str) -> None:
        nonlocal prompt_tokens, completion_tokens, cost_total, estimated_any
        p_tokens, c_tokens, was_estimated = _usage_counts(usage, prompt, text)
        prompt_tokens += p_tokens
        completion_tokens += c_tokens
        estimate = _estimate_cost(model, p_tokens, c_tokens)
        cost_total = cost_total + estimate if cost_total is not None and estimate is not None else None
        estimated_any = estimated_any or was_estimated

    try:
        client = factory(api_key)
        answer, usage = request(user_content)
        if answer:
            add_usage(usage, user_content, answer)
        issues = validate_answer(answer, facts) if answer else ["The visible answer was empty."]
        stage = "gemini"
        if issues:
            LOGGER.warning("Gemini answer rejected key_slot=GEMINI_API_KEY model=%s raw_answer=%r violations=%s", model, answer, issues)
            retry_contents = (
                f"{user_content}\n\nRegenerate a complete answer. Fix every hard violation listed below. "
                "Citations are optional; if included, use only IDs present in the supplied facts. Keep the answer natural, answer the question directly, and use only supplied facts.\nValidation feedback:\n- "
                + "\n- ".join(issues)
                + f"\nPrior answer:\n{answer}"
            )
            answer, retry_usage = request(retry_contents)
            if answer:
                add_usage(retry_usage, retry_contents, answer)
            retry_issues = validate_answer(answer, facts) if answer else ["The regenerated visible answer was empty."]
            stage = "gemini_regenerated"
            if retry_issues:
                LOGGER.warning("Gemini regenerated answer rejected key_slot=GEMINI_API_KEY model=%s raw_answer=%r violations=%s", model, answer, retry_issues)
                return LLMAnswer(FALLBACK_MESSAGE, "gemini", model, None, prompt_tokens, completion_tokens,
                                 prompt_tokens + completion_tokens, cost_total, estimated_any, False, stage)

        LOGGER.info(
            "Gemini answer key_slot=GEMINI_API_KEY model=%s prompt_tokens=%d completion_tokens=%d total_tokens=%d estimated_cost_usd=%s usage_estimated=%s duration_ms=%d",
            model,
            prompt_tokens,
            completion_tokens,
            prompt_tokens + completion_tokens,
            cost_total,
            estimated_any,
            round((time.monotonic() - started) * 1000),
        )
        return LLMAnswer(
            answer=answer,
            provider="gemini",
            model=model,
            api_key_slot="GEMINI_API_KEY",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=cost_total,
            usage_is_estimated=estimated_any,
            succeeded=True,
            validation_stage=stage,
        )
    except Exception as error:
        # Provider exceptions may contain request or credential details; log only class.
        LOGGER.warning(
            "Gemini attempt failed key_slot=GEMINI_API_KEY model=%s error=%s prompt_tokens=%d completion_tokens=%d",
            model,
            type(error).__name__,
            prompt_tokens or _approx_tokens(user_content),
            completion_tokens,
        )
        return LLMAnswer(
            FALLBACK_MESSAGE,
            "gemini",
            model,
            None,
            prompt_tokens,
            completion_tokens,
            prompt_tokens + completion_tokens,
            cost_total,
            estimated_any,
            False,
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                LOGGER.debug("Gemini client cleanup failed key_slot=GEMINI_API_KEY")
