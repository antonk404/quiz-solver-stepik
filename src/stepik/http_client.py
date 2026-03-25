"""Низкоуровневый HTTP-клиент для Stepik API (aiohttp)."""

import logging
import asyncio
from types import TracebackType
from typing import Any, Self

import aiohttp
from playwright.async_api import Page
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .exceptions import (
    StepikAPIError,
    StepikAuthError,
    StepikNotFoundError,
    StepikAPITransientError,
)

logger = logging.getLogger(__name__)


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, StepikAPITransientError):
        return True
    if isinstance(exc, (aiohttp.ClientError, asyncio.TimeoutError)):
        return True
    return False


_retry_http = retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)


class StepikHTTPClient:
    """HTTP-транспорт для Stepik API.

    Используется ТОЛЬКО через ``async with``::

        async with StepikHTTPClient(page) as http:
            data = await http.get("/steps/12345")
    """

    BASE = "https://stepik.org/api"

    def __init__(self, page: Page) -> None:
        self._page = page
        self._session: aiohttp.ClientSession | None = None
        self._csrf: str = ""

    # ── Context Manager ────────────────────────────────────────

    async def __aenter__(self) -> Self:
        raw_cookies = await self._page.context.cookies("https://stepik.org")

        cookie_parts: list[str] = []
        for c in raw_cookies:
            cookie_parts.append(f"{c['name']}={c['value']}")
            if c["name"] == "csrftoken":
                self._csrf = c["value"]

        if not self._csrf:
            logger.warning("CSRF-токен не найден в cookies.")

        self._session = aiohttp.ClientSession(
            cookie_jar=aiohttp.DummyCookieJar(),
            headers={
                "Cookie": "; ".join(cookie_parts),
                "Referer": "https://stepik.org",
                "X-CSRFToken": self._csrf,
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        )
        logger.info(
            "HTTP-клиент инициализирован (csrf=%s…)",
            self._csrf[:8] if self._csrf else "N/A",
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
            logger.info("HTTP-сессия закрыта.")
        self._session = None

        if exc_val is not None:
            logger.error("HTTP-клиент закрыт из-за ошибки: %s", exc_val)

    # ── Session ────────────────────────────────────────────────

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise StepikAPIError(
                "HTTP-клиент не активен. "
                "Используйте 'async with StepikHTTPClient(page)'."
            )
        return self._session

    # ── Response check ─────────────────────────────────────────

    @staticmethod
    async def _check_response(resp: aiohttp.ClientResponse) -> None:
        status = resp.status
        if status < 400:
            return

        if status == 401:
            raise StepikAuthError("Сессия истекла (401).")
        if status == 403:
            raise StepikAuthError("Доступ запрещён (403).")
        if status == 404:
            raise StepikNotFoundError(f"Не найдено: {resp.url}")
        if status in (429, 500, 502, 503, 504):
            body = await resp.text()
            raise StepikAPITransientError(status, body[:200])

        body = await resp.text()
        raise StepikAPIError(f"HTTP {status}: {body[:300]}")

    # ── HTTP methods ───────────────────────────────────────────

    @_retry_http
    async def get(self, path: str, **kwargs: Any) -> dict:
        url = f"{self.BASE}{path}"
        logger.debug("GET %s", url)
        async with self.session.get(url, **kwargs) as resp:
            await self._check_response(resp)
            return await resp.json()

    @_retry_http
    async def post(self, path: str, json: dict) -> dict:
        url = f"{self.BASE}{path}"
        logger.debug("POST %s", url)
        async with self.session.post(url, json=json) as resp:
            await self._check_response(resp)
            return await resp.json()
