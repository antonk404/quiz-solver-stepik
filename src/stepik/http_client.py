"""HTTP-клиент для Stepik API с автообновлением токена."""

import logging
import asyncio
from types import TracebackType
from typing import Any, Self

import aiohttp
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .auth import StepikAuth
from .exceptions import (
    StepikAPIError,
    StepikAuthError,
    StepikNotFoundError,
    StepikAPITransientError,
)

logger = logging.getLogger(__name__)


def _is_transient(exc: BaseException) -> bool:
    """Возвращает `True` для временных сетевых/API ошибок."""
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

    Автоматически обновляет токен при истечении::

        auth = StepikAuth(client_id, client_secret, email, password)
        async with StepikHTTPClient(auth) as http:
            data = await http.get("/steps/12345")
            # Даже через 5 часов — токен обновится сам
    """

    BASE = "https://stepik.org/api"

    def __init__(self, auth: StepikAuth) -> None:
        """Сохраняет auth-объект и подготавливает HTTP-сессию."""
        self._auth = auth
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> Self:
        """Открывает сессию с актуальным Bearer-токеном."""
        token = await self._auth.get_token()

        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        )
        logger.info("HTTP-клиент инициализирован")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Закрывает HTTP-сессию при выходе из контекста."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("HTTP-сессия закрыта.")

    @property
    def session(self) -> aiohttp.ClientSession:
        """Возвращает активную сессию или бросает ошибку состояния."""
        if self._session is None or self._session.closed:
            raise StepikAPIError("HTTP-клиент не активен.")
        return self._session

    async def _refresh_if_needed(self) -> None:
        """Обновляет токен и пересоздает сессию, если срок истекает."""
        if not self._auth.is_expired:
            return

        logger.info("🔄 Токен истекает — обновление...")
        new_token = await self._auth.get_token()

        # Пересоздаём сессию с новым токеном
        old = self._session
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {new_token}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        )

        if old and not old.closed:
            await old.close()

        logger.info("✅ Сессия обновлена с новым токеном")

    @staticmethod
    async def _check_response(resp: aiohttp.ClientResponse) -> None:
        """Преобразует HTTP-статусы в типизированные исключения Stepik."""
        status = resp.status
        if status < 400:
            return
        if status == 401:
            raise StepikAuthError("Токен истёк (401).")
        if status == 403:
            raise StepikAuthError("Доступ запрещён (403).")
        if status == 404:
            raise StepikNotFoundError(f"Не найдено: {resp.url}")
        if status in (429, 500, 502, 503, 504):
            body = await resp.text()
            raise StepikAPITransientError(status, body[:200])
        body = await resp.text()
        raise StepikAPIError(f"HTTP {status}: {body[:300]}")

    @_retry_http
    async def get(self, path: str, **kwargs: Any) -> dict:
        """Выполняет GET-запрос с retry и автообновлением токена."""
        await self._refresh_if_needed()
        url = f"{self.BASE}{path}"
        logger.debug("GET %s", url)
        try:
            async with self.session.get(url, **kwargs) as resp:
                await self._check_response(resp)
                return await resp.json()
        except StepikAuthError:
            # Токен мог истечь между проверкой и запросом
            logger.warning("401 — принудительное обновление токена")
            self._auth._expires_at = 0  # форсируем обновление
            await self._refresh_if_needed()
            async with self.session.get(url, **kwargs) as resp:
                await self._check_response(resp)
                return await resp.json()

    @_retry_http
    async def post(self, path: str, json: dict) -> dict:
        """Выполняет POST-запрос с retry и автообновлением токена."""
        await self._refresh_if_needed()
        url = f"{self.BASE}{path}"
        logger.debug("POST %s", url)
        try:
            async with self.session.post(url, json=json) as resp:
                await self._check_response(resp)
                return await resp.json()
        except StepikAuthError:
            logger.warning("401 — принудительное обновление токена")
            self._auth._expires_at = 0
            await self._refresh_if_needed()
            async with self.session.post(url, json=json) as resp:
                await self._check_response(resp)
                return await resp.json()
