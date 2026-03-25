"""Пакетная обработка: урок и курс."""

import logging
import asyncio

from src.stepik import StepikAPIClient

from .step_processor import StepProcessor

logger = logging.getLogger(__name__)


class CourseProcessor:
    """Итерирует по шагам урока/курса.

    Использует StepProcessor для решения каждого шага::

        step_proc = StepProcessor(page, ai, api, registry)
        course_proc = CourseProcessor(step_proc)
        solved = await course_proc.process_course(6667)
    """

    def __init__(self, step_processor: StepProcessor) -> None:
        self._step = step_processor

    @property
    def _api(self) -> StepikAPIClient:
        return self._step.api

    @property
    def _nav(self):
        return self._step.nav

    @property
    def _delay(self) -> float:
        return self._step.delay

    # ── Урок ───────────────────────────────────────────────────

    async def process_lesson(self) -> int:
        """Решает все шаги текущего урока.

        Определяет урок из текущего URL.
        Возвращает количество решённых шагов.
        """
        parsed = self._api.parse_url(self._step.page.url)
        if not parsed:
            logger.error(
                "Не удалось определить урок: %s",
                self._step.page.url,
            )
            return 0

        step_ids = await self._api.get_lesson_step_ids(parsed.lesson_id)
        total = len(step_ids)
        solved = 0

        for pos in range(1, total + 1):
            url = (
                f"https://stepik.org/lesson/"
                f"{parsed.lesson_id}/step/{pos}"
            )
            logger.info("─── Шаг %d/%d ───", pos, total)

            await self._nav.goto(url)

            result = await self._step.process()
            if result.success:
                solved += 1
            else:
                logger.error("Шаг %d не решён.", pos)

            await asyncio.sleep(self._delay)

        logger.info(
            "Урок %d: %d/%d.",
            parsed.lesson_id, solved, total,
        )
        return solved

    # ── Курс ───────────────────────────────────────────────────

    async def process_course(self, course_id: int) -> int:
        """Решает все шаги курса.

        Возвращает количество решённых шагов.
        """
        pairs = await self._api.get_course_steps(course_id)
        total = len(pairs)
        solved = 0

        for i, (lesson_id, step_id) in enumerate(pairs, 1):
            step = await self._api.get_step(step_id)
            url = (
                f"https://stepik.org/lesson/"
                f"{lesson_id}/step/{step.position}"
            )
            logger.info("══ Курс: %d/%d │ %s ══", i, total, url)

            await self._nav.goto(url)

            result = await self._step.process()
            if result.success:
                solved += 1

            await asyncio.sleep(self._delay)

        logger.info(
            "Курс %d: %d/%d.", course_id, solved, total,
        )
        return solved
