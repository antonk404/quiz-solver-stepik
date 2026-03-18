import asyncio
import logging
import sys

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ai_client import AIClient
from browser_manager import BrowserManager
from exceptions import AppError
from logging_config import setup_logging
from config import settings

# Импортируем напрямую из пакета orchestration
from orchestration.auth import ensure_logged_in
from orchestration.navigation import ensure_course_started
from orchestration.step_processor import process_step

setup_logging()
logger = logging.getLogger("Orchestrator")

async def main():
    logger.info("=== Запуск Stepik-Solver ===")

    ai_client = AIClient(temperature=0.2, max_reasks=settings.ai_max_reasks)
    ai_unavailable_notified = False

    async with BrowserManager() as context:
        page = context.pages[0] if context.pages else await context.new_page()

        await ensure_logged_in(page)

        logger.info("Переходим по ссылке: %s", settings.stepik_web)
        await page.goto(settings.stepik_web, wait_until="domcontentloaded")

        await ensure_course_started(page)

        while True:
            logger.info("Ожидание рендеринга шага...")
            await asyncio.sleep(max(0.0, settings.main_loop_delay_sec))

            try:
                step_result = await process_step(page, ai_client)
            except AppError as exc:
                logger.error("Ошибка решения шага: %s", exc)
                break

            if not step_result.success:
                logger.warning("Остановка автоматического прохождения.")
                break

            if step_result.ai_unavailable:
                if not ai_unavailable_notified:
                    logger.warning(
                        "Автоматическое решение временно недоступно (ограничение Gemini по региону). "
                        "Браузер остается открытым для ручного прохождения."
                    )
                    ai_unavailable_notified = True
                continue

            if step_result.advanced_to_next:
                logger.info(">>> Переход на следующий шаг выполнен сразу (ответ уже верный) >>>")
                continue

            try:
                next_btn = page.locator("button.lesson__next-btn:visible").first
                await next_btn.wait_for(state="visible", timeout=5000)
                logger.info(">>> Переход на следующий шаг >>>")
                await next_btn.click()
                await page.wait_for_url("**", timeout=5000)
            except PlaywrightTimeoutError:
                logger.info("Кнопка 'Следующий шаг' не найдена. Возможно, модуль пройден!")
                break

    logger.info("=== Работа Stepik-Solver завершена ===")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа принудительно остановлена (Ctrl+C).")
        sys.exit(0)