"""Точка входа."""

import asyncio
import json
import logging
import os
import sys

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

COOKIES_DIR = os.environ.get("COOKIES_DIR", "./cookies")
COOKIES_FILE = os.path.join(COOKIES_DIR, "stepik_cookies.json")

# Селекторы профиля — признак что залогинен
_PROFILE_SELECTORS = [
    ".navbar__profile-img",
    "[class*=profile-img]",
    "[class*=avatar]",
    "a[href*='/users/']",
]


def _is_docker() -> bool:
    return (
        os.path.exists("/.dockerenv")
        or os.environ.get("DISPLAY") == ":99"
    )


async def _save_cookies(context, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cookies = await context.cookies()
    with open(path, "w") as f:
        json.dump(cookies, f)
    logger.info("💾 Cookies сохранены в %s", path)


async def _load_cookies(context, path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            cookies = json.load(f)
        await context.add_cookies(cookies)
        logger.info("🍪 Cookies загружены из %s", path)
        return True
    except Exception as e:
        logger.warning("Не удалось загрузить cookies: %s", e)
        return False


async def _delete_cookies(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
        logger.info("🗑️ Старые cookies удалены")


async def _check_logged_in(page) -> bool:
    """Проверяет, видны ли элементы профиля на странице."""
    for sel in _PROFILE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def _wait_for_login(page, docker: bool) -> None:
    """Ждёт пока пользователь залогинится."""
    if docker:
        logger.info(
            "\n"
            "══════════════════════════════════════════════\n"
            "  🔑 Откройте http://localhost:6080/vnc.html\n"
            "     и залогиньтесь на Stepik.\n"
            "     Бот автоматически обнаружит вход.\n"
            "══════════════════════════════════════════════"
        )

        selector = ", ".join(_PROFILE_SELECTORS)
        try:
            await page.wait_for_selector(
                selector,
                state="visible",
                timeout=300_000,  # 5 минут
            )
            logger.info("✅ Авторизация обнаружена!")
        except Exception:
            logger.error(
                "⏰ Время ожидания логина истекло (5 минут). "
                "Перезапустите: docker-compose restart"
            )
            sys.exit(1)
    else:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: input("\n🔑 Залогиньтесь в Stepik и нажмите Enter...\n"),
        )

    # Пауза чтобы cookies прогрузились
    await page.wait_for_timeout(3000)


async def main() -> None:
    setup_logging()

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

    docker = _is_docker()
    ai = AIClient()
    registry = create_default_registry()

    async with async_playwright() as pw:
        if docker:
            browser = await pw.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1280,720",
                ],
            )
        else:
            browser = await pw.chromium.launch(headless=False)

        context = await browser.new_context()
        page = await context.new_page()

        # ── Попытка 1: загрузить сохранённые cookies ──
        logged_in = False
        cookies_loaded = await _load_cookies(context, COOKIES_FILE)

        if cookies_loaded:
            await page.goto(course_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)  # даём время на загрузку

            if await _check_logged_in(page):
                logger.info("✅ Вход через сохранённые cookies!")
                logged_in = True
            else:
                logger.warning("⚠️ Сохранённые cookies не работают (истекли)")
                await _delete_cookies(COOKIES_FILE)
                # Чистим cookies в контексте браузера тоже
                await context.clear_cookies()

        # ── Попытка 2: ручной логин ──
        if not logged_in:
            await page.goto(course_url, wait_until="domcontentloaded")
            await _wait_for_login(page, docker)

            if await _check_logged_in(page):
                logger.info("✅ Авторизация успешна!")
                await _save_cookies(context, COOKIES_FILE)
                logged_in = True
            else:
                logger.error("❌ Не удалось авторизоваться")
                await browser.close()
                return

        # ── Основная работа ──
        async with StepikHTTPClient(page) as http:
            api = StepikAPIClient(http)

            # DEBUG: проверяем что API возвращает
            try:
                course_data = await http.get(f"/courses/{course_id}")
                sections = course_data.get("courses", [{}])[0].get("sections", [])
                logger.info("DEBUG: секций в курсе: %d, ids: %s", len(sections), sections[:5])

                if sections:
                    first_section = await http.get(f"/sections/{sections[0]}")
                    units = first_section.get("sections", [{}])[0].get("units", [])
                    logger.info("DEBUG: юнитов в первой секции: %d", len(units))
            except Exception as e:
                logger.error("DEBUG: ошибка API: %s", e)

            step_proc = StepProcessor(page, ai, api, registry)
            course_proc = CourseProcessor(step_proc)

            solved = await course_proc.process_course(course_id)
            logger.info("🎓 Итого: %d шагов.", solved)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
