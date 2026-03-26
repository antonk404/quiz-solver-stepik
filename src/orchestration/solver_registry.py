"""Реестр солверов — маппинг block_type → solver.

Без хардкода: солверы регистрируются явно,
легко добавить новый тип без правки существующего кода (OCP).
"""

import logging

from .solvers import (
    BaseSolver,
    ChoiceSolver,
    MatchingSolver,
    SortingSolver,
    TextSolver,
)

logger = logging.getLogger(__name__)


class SolverRegistry:
    """Хранит соответствие `block_type -> solver` и выдает нужный обработчик."""

    def __init__(self) -> None:
        """Создает пустой реестр солверов."""
        self._solvers: dict[str, BaseSolver] = {}

    def register(self, block_type: str, solver: BaseSolver) -> None:
        """Регистрирует солвер для типа задания."""
        self._solvers[block_type] = solver
        logger.debug("Солвер зарегистрирован: %s → %s",
                      block_type, type(solver).__name__)

    def register_many(
        self, mapping: dict[str, BaseSolver],
    ) -> None:
        """Регистрирует несколько солверов."""
        for block_type, solver in mapping.items():
            self.register(block_type, solver)

    def get(self, block_type: str) -> BaseSolver | None:
        """Возвращает солвер или None."""
        return self._solvers.get(block_type)

    def has(self, block_type: str) -> bool:
        """Проверяет, зарегистрирован ли солвер для типа задания."""
        return block_type in self._solvers

    @property
    def supported_types(self) -> frozenset[str]:
        """Возвращает множество всех зарегистрированных типов заданий."""
        return frozenset(self._solvers.keys())


def create_default_registry() -> SolverRegistry:
    """Фабрика: создаёт реестр со стандартными солверами."""
    registry = SolverRegistry()

    choice = ChoiceSolver()
    matching = MatchingSolver()
    sorting = SortingSolver()
    text = TextSolver()

    registry.register_many({
        "choice": choice,
        "matching": matching,
        "sorting": sorting,
        "string": text,
        "number": text,
        "free-answer": text,
        "math": text,
    })

    logger.info(
        "Реестр солверов: %s",
        ", ".join(sorted(registry.supported_types)),
    )
    return registry
