import logging

from playwright.async_api import Page
from pydantic import BaseModel


class TaskScores(BaseModel):
    """Модель для подсчета весов (эвристик) типов задач."""
    choice: int = 0
    string: int = 0
    ordering: int = 0
    table: int = 0

    def get_best_match(self) -> tuple[str, int]:
        """Возвращает кортеж (название_типа, количество_очков)."""
        # Превращаем модель обратно в словарь только для поиска максимума
        data = self.model_dump()
        base_type = max(data, key=data.get)
        return base_type, data[base_type]


class TaskDetector:
    def __init__(self, page: Page):
        self.page: Page = page
        self.logger = logging.getLogger("Detector")

    async def detect_task_type(self) -> str:
        scores = TaskScores()

        # Специфичные селекторы Stepik
        if await self.page.query_selector(".choice-quiz"):
            scores.choice += 5
        if await self.page.query_selector(".string-quiz"):
            scores.string += 5
        if await self.page.query_selector(".sortable-list"):
            scores.ordering += 10
        if await self.page.query_selector(".matching-quiz"):
            scores.table += 10

        # Роли(ARIA)
        if await self.page.query_selector('[role="radiogroup"]'):
            scores.choice += 8
        if await self.page.query_selector('[role="checkbox"]'):
            scores.choice += 8
        if await self.page.query_selector('table'):
            scores.table += 5

        # Получаем победителя через встроенный метод модели
        best_type, max_score = scores.get_best_match()

        if max_score == 0:
            self.logger.warning("Не удалось определить тип задачи (все счетчики = 0). Используется тип по умолчанию: unknown.")
            return "unknown"

        self.logger.info(f"Определен тип задачи: {best_type} (Очки: {max_score})")
        return best_type
    