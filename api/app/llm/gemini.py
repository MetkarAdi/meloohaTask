from __future__ import annotations

import logging
import os
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
from .validation import safe_violation_codes, validate_answer
from .provider_errors import classify_provider_error, retry_delay
from .sections import SectionParser, section_answer
from .language import LANGUAGE_RULE

LOGGER = logging.getLogger("melooha.llm.gemini")
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _default_client(api_key: str):
    from google import genai

    timeout = _positive_float_env("GEMINI_TIMEOUT_SECONDS", 20.0)
    # Disable SDK-managed retries: the orchestrator applies the bounded retry policy
    # and can therefore avoid retrying invalid credentials or malformed requests.
    return genai.Client(
        api_key=api_key,
        http_options={"timeout": int(timeout * 1000), "retry_options": {"attempts": 1}},
    )


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _extract_stream(response: Any, *, facts: Sequence[str] = (), question: str = "", on_section: Callable[[str, str], None] | None = None) -> tuple[str, Any]:
    parts: list[str] = []
    usage = None
    parser = SectionParser()
    for chunk in response:
        usage = _read(chunk, "usage_metadata", usage)
        text = _read(chunk, "text")
        if text:
            value = str(text)
            parts.append(value)
            if on_section:
                for section in parser.feed(value):
                    if section.text and not validate_answer(section.text, facts, question):
                        on_section(section.title, section.text)
    if on_section:
        for section in parser.feed("", final=True):
            if section.text and not validate_answer(section.text, facts, question):
                on_section(section.title, section.text)
    if usage is not None:
        usage = {
            "prompt_tokens": _read(usage, "prompt_token_count"),
            "completion_tokens": _read(usage, "candidates_token_count"),
        }
    raw = "".join(parts).strip()
    parsed = SectionParser().feed(raw, final=True)
    return (section_answer(parsed) if parsed else raw), usage


def generate_gemini_answer(
    question: str,
    facts: Sequence[str],
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    client_factory: Callable[[str], Any] | None = None,
    stream: bool = True,
    on_section: Callable[[str, str], None] | None = None,
    on_reset: Callable[[], None] | None = None,
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
        try:
            retry_limit = min(3, max(0, int(os.getenv("GEMINI_MAX_TRANSIENT_RETRIES", "1"))))
        except ValueError:
            retry_limit = 1
        base_delay = _positive_float_env("LLM_RETRY_BASE_DELAY_SECONDS", 0.25)
        for retry_index in range(retry_limit + 1):
            try:
                response = client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=config,
                )
                # Buffer the complete Gemini stream so provider failover can never splice
                # a partial Gemini answer into the Groq answer.
                return _extract_stream(response, facts=facts, question=question, on_section=on_section)
            except Exception as error:
                category = classify_provider_error(error)
                if category not in {"transient", "rate_limited"} or retry_index >= retry_limit:
                    raise
                delay = retry_delay(base_delay, retry_index)
                LOGGER.warning("Gemini transient failure model=%s category=%s retry=%d/%d delay_seconds=%.2f", model, category, retry_index + 1, retry_limit, delay)
                if delay:
                    time.sleep(delay)

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
        issues = validate_answer(answer, facts, question) if answer else ["The visible answer was empty."]
        stage = "gemini"
        if issues:
            if on_reset:
                on_reset()
            LOGGER.warning("Gemini answer rejected key_slot=GEMINI_API_KEY model=%s answer_chars=%d violation_count=%d violation_codes=%s", model, len(answer), len(issues), safe_violation_codes(issues))
            retry_contents = (
                f"{user_content}\n\nRegenerate a complete answer. Fix every hard violation listed below. {LANGUAGE_RULE} "
                "Citations are optional; if included, use only IDs present in the supplied facts. Keep the answer natural, answer the question directly, and use only supplied facts.\nValidation feedback:\n- "
                + "\n- ".join(issues)
                + f"\nPrior answer:\n{answer}\n{LANGUAGE_RULE}"
            )
            answer, retry_usage = request(retry_contents)
            if answer:
                add_usage(retry_usage, retry_contents, answer)
            retry_issues = validate_answer(answer, facts, question) if answer else ["The regenerated visible answer was empty."]
            stage = "gemini_regenerated"
            if retry_issues:
                LOGGER.warning("Gemini regenerated answer rejected key_slot=GEMINI_API_KEY model=%s answer_chars=%d violation_count=%d violation_codes=%s", model, len(answer), len(retry_issues), safe_violation_codes(retry_issues))
                return LLMAnswer(FALLBACK_MESSAGE, "gemini", model, None, prompt_tokens, completion_tokens,
                                 prompt_tokens + completion_tokens, cost_total, estimated_any, False, stage,
                                 failure_reason=f"validation_failed:{safe_violation_codes(retry_issues)}")

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
        if on_reset:
            on_reset()
        # Provider exceptions may contain request or credential details; log only class.
        category = classify_provider_error(error)
        LOGGER.warning(
            "Gemini attempt failed key_slot=GEMINI_API_KEY model=%s category=%s error_type=%s prompt_tokens=%d completion_tokens=%d",
            model,
            category,
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
            failure_reason=f"{category}:{type(error).__name__}",
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                LOGGER.debug("Gemini client cleanup failed key_slot=GEMINI_API_KEY")
