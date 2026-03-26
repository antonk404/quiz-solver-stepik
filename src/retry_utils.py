"""Retry-стратегии для API-вызовов."""

import logging
import re

from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception,
    before_sleep_log,
)

from src.config import settings

logger = logging.getLogger(__name__)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    """Проверяет, содержит ли текст хотя бы один маркер из набора."""
    return any(token in text for token in tokens)


def _extract_retry_delay_seconds(error_text: str) -> float | None:
    """Извлекает рекомендованный delay из текста ошибки."""
    patterns = (
        r"PLEASE RETRY IN\s+(\d+(?:\.\d+)?)S",
        r"RETRYDELAY['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)S",
    )
    upper = error_text.upper()
    for pattern in patterns:
        match = re.search(pattern, upper)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


_NON_RETRIABLE = (
    "404", "NOT_FOUND", "INVALID_ARGUMENT",
    "PERMISSION_DENIED", "UNAUTHENTICATED",
)

_DAILY_QUOTA = (
    "GENERATEREQUESTSPERDAYPERPROJECTPERMODEL-FREETIER",
    "PERDAY",
)

_HARD_QUOTA = (
    "LIMIT: 0",
    "FREE_TIER_REQUESTS, LIMIT: 0",
    "FREE_TIER_INPUT_TOKEN_COUNT, LIMIT: 0",
)

_RETRIABLE = (
    "429", "RESOURCE_EXHAUSTED", "UNAVAILABLE",
    "DEADLINE_EXCEEDED", "INTERNAL", "TIMEOUT",
    "TIMED OUT", "CONNECTION", "500", "503",
)


def is_retriable_api_error(exc: Exception) -> bool:
    """Ретраим только транзиентные ошибки API."""
    text = str(exc).upper()

    if _contains_any(text, _DAILY_QUOTA):
        return False
    if _contains_any(text, _HARD_QUOTA):
        return False
    if _contains_any(text, _NON_RETRIABLE):
        return False

    return _contains_any(text, _RETRIABLE)


def _api_wait_seconds(retry_state) -> float:
    """Backoff: max(экспонента, серверный retryDelay + буфер)."""
    attempt = max(1, retry_state.attempt_number)

    if settings.fast_mode:
        base_wait = min(4.0, max(1.0, float(2 ** (attempt - 1))))
    else:
        base_wait = min(20.0, max(4.0, float(2 ** attempt)))

    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is None:
        return base_wait

    server_delay = _extract_retry_delay_seconds(str(exc))
    if server_delay is None:
        return base_wait

    return max(base_wait, server_delay + 1.0)


retry_on_api = retry(
    stop=stop_after_attempt(
        max(1, settings.api_retry_attempts) if settings.fast_mode else 5
    ),
    wait=_api_wait_seconds,
    retry=retry_if_exception(is_retriable_api_error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
