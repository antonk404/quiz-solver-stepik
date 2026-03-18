import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


async def dismiss_cookie_banner(page: Page) -> None:
    """Закрывает плашку с куки, чтобы она не перекрывала клики по ответам."""
    try:
        btn = page.locator("button", has_text="Хорошо").first
        if await btn.is_visible(timeout=1000):
            await btn.click()
            logger.debug("Плашка с куки успешно закрыта.")
    except PlaywrightTimeoutError:
        # Баннер отсутствует на странице — это штатный сценарий
        pass


async def ensure_course_started(page: Page) -> None:
    """Если бот оказался на странице оглавления курса, нажимает 'Продолжить'."""
    if "/course/" not in page.url:
        return

    logger.info("Мы на странице Оглавления курса. Ищем кнопку старта...")
    try:
        start_btn = page.locator("text='Продолжить'").first
        await start_btn.wait_for(state="visible", timeout=5000)
        await start_btn.click()

        await page.wait_for_url("**/lesson/**", timeout=10000)
        logger.info("Успешно перешли в урок: %s", page.url)
    except PlaywrightTimeoutError:
        logger.error("Не удалось найти кнопку 'Продолжить'. Вы записаны на этот курс?")
        raise
