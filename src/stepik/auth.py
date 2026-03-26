"""Авторизация через Stepik OAuth2 API."""

import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

STEPIK_TOKEN_URL = "https://stepik.org/oauth2/token/"


class StepikAuth:
    """Управляет OAuth2 токеном Stepik и его автообновлением."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        email: str,
        password: str,
        # Обновлять за 5 минут до истечения
        refresh_margin: int = 300,
    ) -> None:
        """Сохраняет OAuth2-креды и параметры раннего обновления."""
        self._client_id = client_id
        self._client_secret = client_secret
        self._email = email
        self._password = password
        self._refresh_margin = refresh_margin

        self._token: str = ""
        self._expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        """Показывает, что токен истек или скоро истечет."""
        return time.time() >= (self._expires_at - self._refresh_margin)

    async def get_token(self) -> str:
        """Возвращает актуальный токен, запрашивая новый при необходимости."""
        if self._token and not self.is_expired:
            return self._token

        await self._fetch_token()
        return self._token

    async def _fetch_token(self) -> None:
        """Запрашивает новый access token через OAuth2 password grant."""
        logger.info("🔑 Получение нового токена Stepik...")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                STEPIK_TOKEN_URL,
                data={
                    "grant_type": "password",
                    "username": self._email,
                    "password": self._password,
                },
                auth=aiohttp.BasicAuth(
                    self._client_id, self._client_secret
                ),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "Ошибка авторизации: %s %s",
                        resp.status, body,
                    )
                    raise RuntimeError(
                        f"Stepik auth failed: {resp.status}"
                    )

                data = await resp.json()
                self._token = data["access_token"]
                # expires_in — время жизни в секундах (обычно 36000)
                expires_in = data.get("expires_in", 36000)
                self._expires_at = time.time() + expires_in

                logger.info(
                    "✅ Токен получен (истекает через %d мин)",
                    expires_in // 60,
                )
