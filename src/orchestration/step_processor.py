"""Обработка одного шага — класс StepProcessor."""

import logging
import asyncio

from pydantic import BaseModel, ConfigDict
from playwright.async_api import Page

from src.ai_client import AIClient
from src.config import settings
from src.exceptions import (
    AIClientResponseError,
    DOMElementNotFoundError,
    InvalidAnswerIndicesError,
)
from src.stepik import (
    StepikAPIClient,
    StepikAPIError,
    StepikAuthError,
)

from .navigation import Navigator
from .solver_registry import SolverRegistry
from .step_checker import StepChecker

logger = logging.getLogger(__name__)

_EXPECTED_ERRORS = (
    AIClientResponseError,
    DOMElementNotFoundError,
    InvalidAnswerIndicesError,
)


class ProcessStepResult(BaseModel):
    """Результат обработки одного шага."""
    model_config = ConfigDict(frozen=True)

    success: bool
    advanced_to_next: bool = False


class StepProcessor:
    """Решает один шаг: проверка → решение → отправка.

    Использование::

        processor = StepProcessor(page, ai, api, registry)
        result = await processor.process()
    """

    def __init__(
        self,
        page: Page,
        ai: AIClient,
        api: StepikAPIClient,
        registry: SolverRegistry,
        max_attempts: int | None = None,
        delay: float | None = None,
    ) -> None:
        self.page = page
        self.ai = ai
        self.api = api
        self.registry = registry
        self.max_attempts = max_attempts or max(1, settings.step_solve_attempts)
        self.delay = delay or settings.api_delay_between_steps_sec

        self.nav = Navigator(page)
        self.checker = StepChecker(api)

    # ── Публичный метод ────────────────────────────────────────

    async def process(self) -> ProcessStepResult:
        """Основная точка входа: решает текущий шаг."""
        await self.nav.dismiss_cookie_banner()

        # 1. URL → step_id
        parsed = self.api.parse_url(self.page.url)
        if not parsed:
            logger.info("Не шаг: %s", self.page.url)
            return ProcessStepResult(success=True)

        try:
            step_id = await self.checker.resolve_step_id(parsed)
        except StepikAPIError as exc:
            logger.error("Не определён step_id: %s", exc)
            return ProcessStepResult(success=False)

        # 2. Уже решён?
        if await self.checker.is_already_passed(step_id):
            logger.info("Шаг %d уже решён ✔", step_id)
            return await self._advance()

        # 3. Данные шага
        try:
            step = await self.checker.get_step(step_id)
        except StepikAuthError:
            logger.error("Сессия истекла.")
            return ProcessStepResult(success=False)
        except StepikAPIError as exc:
            logger.error("Ошибка шага: %s", exc)
            return ProcessStepResult(success=False)

        logger.info(
            "═══ Шаг %d │ %s │ урок %d pos %d ═══",
            step_id, step.block_type,
            parsed.lesson_id, parsed.step_position,
        )

        # 4. Пропуск текста/видео
        if self.checker.should_skip(step):
            logger.info("Тип «%s» — пропуск.", step.block_type)
            return await self._advance()

        # 5. Есть ли солвер?
        solver = self.registry.get(step.block_type)
        if solver is None:
            logger.warning("Нет солвера для «%s».", step.block_type)
            return ProcessStepResult(success=True)

        # 6. Цикл попыток
        return await self._attempt_loop(step_id, step, solver)

    # ── Цикл попыток ──────────────────────────────────────────

    async def _attempt_loop(self, step_id, step, solver):
        """Пробует решить шаг до max_attempts раз."""
        for num in range(1, self.max_attempts + 1):
            try:
                attempt = await self.api.create_attempt(step_id)
                logger.info(
                    "Попытка %d/%d (id=%d)",
                    num, self.max_attempts, attempt.attempt_id,
                )

                reply = await solver.solve(
                    self.api, self.ai, step, attempt,
                )
                logger.debug("Reply: %s", reply)

                sub_id = await self.api.submit_answer(
                    attempt.attempt_id, reply,
                )
                status = await self.api.poll_status(sub_id)

                result = self._handle_status(status, step_id, num)

                if result.success:
                    await self.nav.reload()
                    advanced = await self.nav.go_next_step()
                    return ProcessStepResult(
                        success=True, advanced_to_next=advanced,
                    )

                # wrong — повторить или вернуть неудачу
                if num < self.max_attempts:
                    await asyncio.sleep(self.delay)
                    continue
                return result

            except _EXPECTED_ERRORS as exc:
                logger.error("Попытка %d: %s", num, exc)
                if num < self.max_attempts:
                    continue
                return ProcessStepResult(success=False)

            except StepikAuthError:
                logger.error("Сессия API истекла.")
                return ProcessStepResult(success=False)

            except StepikAPIError as exc:
                logger.error("API: %s", exc)
                return ProcessStepResult(success=False)

        return ProcessStepResult(success=False)

    # ── Обработка статуса ──────────────────────────────────────

    def _handle_status(
        self,
        status: str,
        step_id: int,
        attempt_num: int,
    ) -> ProcessStepResult:
        """Интерпретирует статус submission."""
        if status == "correct":
            logger.info("✅ Шаг %d решён!", step_id)
            return ProcessStepResult(success=True)

        if status == "wrong":
            logger.warning(
                "❌ Неверно (%d/%d).",
                attempt_num, self.max_attempts,
            )
            return ProcessStepResult(success=False)

        # timeout, evaluation и прочее
        logger.warning("Статус «%s» — считаем успешным.", status)
        return ProcessStepResult(success=True)

    # ── Навигация ──────────────────────────────────────────────

    async def _advance(self) -> ProcessStepResult:
        """Переходит к следующему шагу."""
        advanced = await self.nav.go_next_step()
        return ProcessStepResult(
            success=True, advanced_to_next=advanced,
        )
