import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.config import settings

logger = logging.getLogger(__name__)


async def ensure_logged_in(page: Page) -> None:
    """Проверяет авторизацию и ждет ручного входа."""
    logger.info("Переход на страницу каталога для проверки сессии...")
    await page.goto(settings.stepik_web, wait_until="domcontentloaded")

    avatar_selector = ".navbar__profile-img"

    try:
        await page.wait_for_selector(avatar_selector, state="visible", timeout=3000)
        logger.info("✅ Сессия найдена. Мы авторизованы!")
        return
    except PlaywrightTimeoutError:
        logger.warning("❌ Мы не авторизованы.")

    logger.info("Ожидание ручной авторизации... Пожалуйста, войдите в аккаунт.")
    await page.wait_for_selector(avatar_selector, state="visible", timeout=0)
    logger.info("✅ Успешная авторизация! Сессия сохранена.")
