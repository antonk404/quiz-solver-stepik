import logging
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext

from config import settings


logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(self):
        self._playwright = None
        self.context: Optional[BrowserContext] = None

    async def __aenter__(self) -> BrowserContext:
        """Запуск браузера при входе в блок with."""
        self._playwright = await async_playwright().start()

        # Убеждаемся, что папка для профиля существует
        settings.stepik_user_data_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Запуск браузера. Профиль: %s", settings.stepik_user_data_dir)

        # launch_persistent_context сохраняет куки, кэш и localStorage
        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=settings.stepik_user_data_dir,
            headless=settings.headless,
            # Базовая маскировка, чтобы Stepik не ругался на автоматизацию
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )

        # Устанавливаем глобальный таймаут из конфига
        self.context.set_default_timeout(settings.timeout)

        return self.context

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Гарантированное закрытие браузера при выходе или ошибке."""
        if self.context is not None:
            await self.context.close()
            self.context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

        if exc_type:
            logger.error("Браузер закрыт из-за ошибки: %s", exc_val)
        else:
            logger.info("Браузер штатно закрыт.")
