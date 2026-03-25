"""Точка входа."""

import asyncio
import logging

from playwright.async_api import async_playwright

from src.config import settings
from src.logging_config import setup_logging
from src.ai_client import AIClient
from src.stepik import StepikHTTPClient, StepikAPIClient
from src.stepik.utils import parse_course_id
from src.orchestration import (
    create_default_registry,
    StepProcessor,
    CourseProcessor,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()

    # Валидация на старте
    course_url = settings.stepik_course_url
    if not course_url:
        logger.error(
            "Укажите STEPIK_COURSE_URL в .env\n"
            "Пример: STEPIK_COURSE_URL="
            "https://stepik.org/course/6667/syllabus"
        )
        return

    course_id = parse_course_id(course_url)
    if not course_id:
        logger.error("Не удалось извлечь ID курса из URL: %s", course_url)
        return

    logger.info("Курс: %s (id=%d)", course_url, course_id)

    ai = AIClient()
    registry = create_default_registry()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(course_url, wait_until="domcontentloaded")
        input("\n🔑 Залогиньтесь в Stepik и нажмите Enter...\n")

        async with StepikHTTPClient(page) as http:
            api = StepikAPIClient(http)

            step_proc = StepProcessor(page, ai, api, registry)
            course_proc = CourseProcessor(step_proc)

            solved = await course_proc.process_course(course_id)
            logger.info("🎓 Итого: %d шагов.", solved)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
