import logging

from playwright.async_api import Page
from config import settings


logger = logging.getLogger(__name__)


async def ensure_logged_in(page: Page) -> None:
    """Проверяет авторизацию и ждет ручного входа, если нужно."""
    logger.info("Переход на главную страницу Stepik...")
    await page.goto(settings.stepik_web)

    avatar_selector = ".navbar__profile-img"

    try:
        # Пытаемся быстро найти аватарку (таймаут 3 секунды)
        await page.wait_for_selector(avatar_selector, timeout=3000)
        logger.info("✅ Сессия найдена. Мы уже авторизованы!")
        return
    except Exception as exc:
        logger.error(f"❌ Мы не авторизованы. Ошибка {exc}")

    logger.info("Пожалуйста, авторизуйтесь в открывшемся окне браузера.")
    logger.info("Скрипт ожидает появления вашего профиля (аватарки)...")

    # Ждем бесконечно (timeout=0), пока пользователь сам не залогинится
    await page.wait_for_selector(avatar_selector, timeout=0)
    logger.info("✅ Успешная авторизация! Сессия сохранена в папку.")
