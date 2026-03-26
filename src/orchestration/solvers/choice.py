"""Солвер для choice с учётом предыдущей ошибки."""

import logging

from src.ai_client import AIClient
from src.exceptions import DOMElementNotFoundError
from src.stepik import (
    StepikAPIClient,
    StepData,
    AttemptData,
    build_choice_reply,
    strip_html,
)

from .base import BaseSolver

logger = logging.getLogger(__name__)


class ChoiceSolver(BaseSolver):

    async def solve(
        self,
        api: StepikAPIClient,
        ai: AIClient,
        step: StepData,
        attempt: AttemptData,
        previous_reply: dict | None = None,
    ) -> dict:
        raw_opts = step.source.options or attempt.dataset.get("options", [])
        texts = self._extract_texts(raw_opts)

        if not texts:
            raise DOMElementNotFoundError("Варианты ответов не найдены.")

        # Формируем подсказку
        hint = (
            " (можно выбрать несколько)"
            if step.is_multiple_choice
            else " (выберите один)"
        )

        question = step.question_text + hint

        # Если есть предыдущий неверный ответ — сообщаем AI
        if previous_reply is not None:
            wrong_indices = [
                i for i, v in enumerate(previous_reply.get("choices", []))
                if v
            ]
            wrong_texts = [texts[i] for i in wrong_indices if i < len(texts)]
            question += (
                f"\n\nВНИМАНИЕ: предыдущий ответ был НЕВЕРНЫМ. "
                f"Неправильные варианты: {wrong_texts}. "
                f"Выбери ДРУГОЙ ответ."
            )
            logger.info("Повторная попытка: исключаем %s", wrong_texts)

        resp = await ai.solve_choice_task(question, texts)
        return build_choice_reply(resp.selected_indices, len(raw_opts))

    @staticmethod
    def _extract_texts(raw_opts: list) -> list[str]:
        texts: list[str] = []
        for o in raw_opts:
            if isinstance(o, dict):
                texts.append(strip_html(o.get("text", "")))
            else:
                texts.append(strip_html(str(o)))
        return [t for t in texts if t]
