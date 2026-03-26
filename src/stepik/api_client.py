"""Высокоуровневый клиент Stepik API."""

import logging
import asyncio

from .exceptions import StepikNotFoundError, StepikAPIError
from .http_client import StepikHTTPClient
from .schemas import (
    StepData,
    AttemptData,
    StepsResponse,
    AttemptsResponse,
    SubmissionsResponse,
    LessonsResponse,
    CoursesResponse,
    SectionsResponse,
    UnitsResponse,
)
from .utils import strip_html, parse_step_url

logger = logging.getLogger(__name__)


class StepikAPIClient:
    """Бизнес-логика Stepik API.

    Не владеет HTTP-сессией — получает готовый ``StepikHTTPClient``::

        async with StepikHTTPClient(page) as http:
            api = StepikAPIClient(http)
            step = await api.get_step(12345)
    """

    def __init__(self, http: StepikHTTPClient) -> None:
        self._http = http
        self._lesson_cache: dict[int, list[int]] = {}

    # ── URL ────────────────────────────────────────────────────

    @staticmethod
    def parse_url(url: str):
        """Парсит URL шага и возвращает `ParsedStepURL` или `None`."""
        return parse_step_url(url)

    # ── Steps ──────────────────────────────────────────────────

    async def get_step(self, step_id: int) -> StepData:
        """Загружает шаг из API и преобразует его в `StepData`."""
        data = await self._http.get(f"/steps/{step_id}")
        response = StepsResponse.model_validate(data)
        raw = response.steps[0]

        return StepData(
            step_id=raw.id,
            lesson_id=raw.lesson,
            position=raw.position,
            block_type=raw.block.name,
            question_html=raw.block.text,
            question_text=strip_html(raw.block.text),
            is_multiple_choice=raw.block.source.is_multiple_choice,
            source=raw.block.source,
        )

    async def get_lesson_step_ids(self, lesson_id: int) -> list[int]:
        """Возвращает список step_id урока, используя локальный кэш."""
        if lesson_id in self._lesson_cache:
            return self._lesson_cache[lesson_id]

        data = await self._http.get(f"/lessons/{lesson_id}")
        response = LessonsResponse.model_validate(data)
        ids = response.lessons[0].steps

        self._lesson_cache[lesson_id] = ids
        logger.debug("Урок %d: %d шагов (кэш).", lesson_id, len(ids))
        return ids

    async def resolve_step_id(self, lesson_id: int, position: int) -> int:
        """Преобразует позицию шага в уроке в реальный `step_id`."""
        ids = await self.get_lesson_step_ids(lesson_id)
        idx = position - 1
        if 0 <= idx < len(ids):
            return ids[idx]
        raise StepikNotFoundError(
            f"Позиция {position} вне диапазона "
            f"(урок {lesson_id}: {len(ids)} шагов)."
        )

    # ── Attempts ───────────────────────────────────────────────

    async def create_attempt(self, step_id: int) -> AttemptData:
        """Создает новую попытку решения шага."""
        data = await self._http.post(
            "/attempts",
            json={"attempt": {"step": str(step_id)}},
        )
        response = AttemptsResponse.model_validate(data)
        raw = response.attempts[0]

        return AttemptData(
            attempt_id=raw.id,
            step_id=step_id,
            dataset=raw.dataset,
            status=raw.status,
        )

    # ── Submissions ────────────────────────────────────────────

    async def submit_answer(self, attempt_id: int, reply: dict) -> int:
        """Отправляет ответ и возвращает идентификатор submission."""
        data = await self._http.post(
            "/submissions",
            json={
                "submission": {
                    "attempt": str(attempt_id),
                    "reply": reply,
                }
            },
        )
        response = SubmissionsResponse.model_validate(data)
        return response.submissions[0].id

    async def poll_status(
        self,
        submission_id: int,
        max_polls: int = 20,
        delay: float = 0.5,
    ) -> str:
        """Ожидает финальный статус проверки submission или таймаут."""
        for _ in range(max_polls):
            data = await self._http.get(f"/submissions/{submission_id}")
            response = SubmissionsResponse.model_validate(data)
            status = response.submissions[0].status

            if status != "evaluation":
                return status
            await asyncio.sleep(delay)

        return "timeout"

    async def is_step_passed(self, step_id: int) -> bool:
        """Проверяет, есть ли у шага хотя бы одна корректная отправка."""
        try:
            data = await self._http.get(
                "/submissions",
                params={
                    "step": step_id,
                    "status": "correct",
                    "page_size": 1,
                },
            )
            response = SubmissionsResponse.model_validate(data)
            return bool(response.submissions)
        except StepikAPIError:
            return False

    # ── Course structure ───────────────────────────────────────

    async def get_course_steps(
        self, course_id: int,
    ) -> list[tuple[int, int]]:
        """Собирает плоский список `(lesson_id, step_id)` для всего курса."""
        data = await self._http.get(f"/courses/{course_id}")
        course = CoursesResponse.model_validate(data).courses[0]

        result: list[tuple[int, int]] = []

        for sec_id in course.sections:
            sec_data = await self._http.get(f"/sections/{sec_id}")
            section = SectionsResponse.model_validate(sec_data).sections[0]

            for unit_id in section.units:
                unit_data = await self._http.get(f"/units/{unit_id}")
                unit = UnitsResponse.model_validate(unit_data).units[0]

                step_ids = await self.get_lesson_step_ids(unit.lesson)
                for sid in step_ids:
                    result.append((unit.lesson, sid))

        logger.info("Курс %d: %d шагов.", course_id, len(result))
        return result
