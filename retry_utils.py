import logging
import re

from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception,
    retry_if_exception_type,
    before_sleep_log,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.config import settings
from exceptions import DOMElementNotFoundError

logger = logging.getLogger(__name__)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _extract_retry_delay_seconds(error_text: str) -> float | None:
    """
    Извлекает рекомендованный сервером delay из текста ошибки.
    Поддерживает форматы:
    - "Please retry in 31.57s."
    - "retryDelay': '31s'"
    """
    patterns = (
        r"PLEASE RETRY IN\s+(\d+(?:\.\d+)?)S",
        r"RETRYDELAY['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)S",
    )
    for pattern in patterns:
        match = re.search(pattern, error_text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _is_retriable_api_error(exc: Exception) -> bool:
    """Ретраим только временные ошибки API; конфигурационные валим сразу."""
    error_text = str(exc).upper()

    # Суточные лимиты free-tier не рассасываются "через минуту" — ретраи бесполезны.
    per_day_quota_tokens = (
        "GENERATEREQUESTSPERDAYPERPROJECTPERMODEL-FREETIER",
        "PERDAY",
    )
    if _contains_any(error_text, per_day_quota_tokens):
        return False

    # Если у проекта/ключа квота равна 0, повторные попытки бесполезны.
    hard_quota_exhausted_tokens = (
        "LIMIT: 0",
        "FREE_TIER_REQUESTS, LIMIT: 0",
        "FREE_TIER_INPUT_TOKEN_COUNT, LIMIT: 0",
    )
    if _contains_any(error_text, hard_quota_exhausted_tokens):
        return False

    non_retriable_tokens = (
        "404",
        "NOT_FOUND",
        "INVALID_ARGUMENT",
        "PERMISSION_DENIED",
        "UNAUTHENTICATED",
    )
    if _contains_any(error_text, non_retriable_tokens):
        return False

    retriable_tokens = (
        "429",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
        "INTERNAL",
        "TIMEOUT",
        "TIMED OUT",
        "CONNECTION",
        "500",
        "503",
    )
    return _contains_any(error_text, retriable_tokens)


def _api_retry_wait_seconds(retry_state) -> float:
    """
    Backoff для API: max(экспонента, retryDelay из ответа API).
    Это уменьшает количество бесполезных 429-запросов.
    """
    attempt = max(1, retry_state.attempt_number)

    if settings.fast_mode:
        exponential_wait = min(4.0, max(1.0, float(2 ** (attempt - 1))))
    else:
        exponential_wait = min(20.0, max(4.0, float(2 ** attempt)))

    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is None:
        return exponential_wait

    retry_delay = _extract_retry_delay_seconds(str(exc).upper())
    if retry_delay is None:
        return exponential_wait

    # +1s буфер, чтобы не стучаться раньше времени, указанного сервером
    return max(exponential_wait, retry_delay + 1.0)


# Стратегия для DOM-действий
dom_retry_attempts = 1 if settings.fast_mode else max(1, settings.retry_attempts)
retry_on_dom = retry(
    stop=stop_after_attempt(dom_retry_attempts),
    wait=lambda state: min(2.0, max(0.2, float(2 ** (state.attempt_number - 1)))) if settings.fast_mode else min(6.0,
                                                                                                                 max(1.0,
                                                                                                                     float(
                                                                                                                         2 ** state.attempt_number))),
    retry=retry_if_exception_type((PlaywrightTimeoutError, DOMElementNotFoundError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)

# Стратегия для API Gemini
retry_on_api = retry(
    stop=stop_after_attempt(max(1, settings.api_retry_attempts) if settings.fast_mode else 5),
    wait=_api_retry_wait_seconds,
    retry=retry_if_exception(_is_retriable_api_error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
