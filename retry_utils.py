import logging

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from config import settings

logger = logging.getLogger(__name__)

# Стратегия для DOM-действий
retry_on_dom = retry(
    stop=stop_after_attempt(settings.retry_attempts),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    retry=retry_if_exception_type(PlaywrightTimeoutError),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)

# Стратегия для API Gemini
retry_on_api = retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=20),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
