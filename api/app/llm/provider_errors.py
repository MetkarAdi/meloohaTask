from __future__ import annotations

from typing import Any


def classify_provider_error(error: Exception) -> str:
    """Classify retry behavior without inspecting or logging provider error text."""
    current: BaseException = error
    while current.__cause__ is not None:
        current = current.__cause__
    status: Any = getattr(current, "status_code", None)
    if status is None:
        status = getattr(current, "code", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None
    if status == 429:
        return "rate_limited"
    if status in {408, 425} or (status is not None and 500 <= status <= 599):
        return "transient"
    if status in {400, 404, 405, 413, 415, 422}:
        return "invalid_request"
    if status in {401, 403}:
        return "invalid_credentials"
    if isinstance(current, (TimeoutError, ConnectionError, OSError)):
        return "transient"
    name = type(current).__name__.casefold()
    if any(fragment in name for fragment in ("timeout", "connection", "ratelimit")):
        return "transient" if "rate" not in name else "rate_limited"
    return "provider_error"


def retry_delay(base_seconds: float, retry_index: int, maximum_seconds: float = 8.0) -> float:
    """Capped exponential backoff duration for a zero-based retry index."""
    return min(maximum_seconds, max(0.0, base_seconds) * (2**retry_index))
