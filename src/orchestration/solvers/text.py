"""Солвер для текстовых заданий."""

import logging

from src.ai_client import AIClient
from src.stepik import (
    StepikAPIClient,
    StepData,
    AttemptData,
    build_string_reply,
    build_number_reply,
)

from .base import BaseSolver

logger = logging.getLogger(__name__)

_NUMBER_TYPES = frozenset({"number", "math"})


class TextSolver(BaseSolver):

    async def solve(
        self,
        api: StepikAPIClient,
        ai: AIClient,
        step: StepData,
        attempt: AttemptData,
        previous_reply: dict | None = None,
    ) -> dict:
        question = step.question_text

        if previous_reply is not None:
            prev_answer = previous_reply.get("text") or previous_reply.get("number", "")
            question += (
                f"\n\nПредыдущий ответ «{prev_answer}» был НЕВЕРНЫМ. "
                f"Дай другой ответ."
            )

        resp = await ai.solve_string_task(question)

        if step.block_type in _NUMBER_TYPES:
            return build_number_reply(resp.answer)
        return build_string_reply(resp.answer)
