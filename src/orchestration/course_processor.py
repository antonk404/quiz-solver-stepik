"""Пакетная обработка курса."""

import logging
import asyncio

from src.stepik import StepikAPIClient

from .step_processor import StepProcessor

logger = logging.getLogger(__name__)


class CourseProcessor:
    """Оркестрирует последовательную обработку всех шагов выбранного курса."""

    def __init__(self, step_processor: StepProcessor) -> None:
        """Сохраняет обработчик шага, через который идет вся работа по курсу."""
        self._step = step_processor

    @property
    def _api(self) -> StepikAPIClient:
        """Возвращает API-клиент из связанного `StepProcessor`."""
        return self._step.api

    @property
    def _delay(self) -> float:
        """Возвращает задержку между обработкой шагов."""
        return self._step.delay

    async def process_course(self, course_id: int) -> int:
        """Проходит все шаги курса и возвращает число успешно обработанных."""
        pairs = await self._api.get_course_steps(course_id)
        total = len(pairs)
        solved = 0

        for i, (lesson_id, step_id) in enumerate(pairs, 1):
            logger.info(
                "══ Курс: %d/%d │ урок %d, шаг %d ══",
                i, total, lesson_id, step_id,
            )

            result = await self._step.process(step_id)
            if result.success:
                solved += 1

            await asyncio.sleep(self._delay)

        logger.info(
            "Курс %d: %d/%d.", course_id, solved, total,
        )
        return solved
