"""Проверка статуса шага."""

import logging

from src.stepik import StepikAPIClient, StepData, ParsedStepURL

logger = logging.getLogger(__name__)

_SKIP_TYPES = frozenset({"text", "video"})


class StepChecker:
    """Определяет статус шага: решён / пропуск / нужно решать."""

    def __init__(self, api: StepikAPIClient) -> None:
        self._api = api

    async def resolve_step_id(self, parsed: ParsedStepURL) -> int:
        return await self._api.resolve_step_id(
            parsed.lesson_id, parsed.step_position,
        )

    async def is_already_passed(self, step_id: int) -> bool:
        return await self._api.is_step_passed(step_id)

    async def get_step(self, step_id: int) -> StepData:
        return await self._api.get_step(step_id)

    @staticmethod
    def should_skip(step: StepData) -> bool:
        return step.block_type in _SKIP_TYPES
