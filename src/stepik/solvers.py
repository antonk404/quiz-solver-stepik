"""Программное решение matching/sorting без AI.

Каждая функция — одна ответственность (SRP):
  _build_correct_mapping  — парсинг правильных пар
  _parse_matching_dataset — парсинг dataset попытки
  _find_option_index      — поиск совпадения (точный + fuzzy)
  _match_terms_to_options — построение ordering
  try_solve_matching      — координатор
"""

import logging

from pydantic import ValidationError

from .schemas import (
    StepData,
    AttemptData,
    SourcePair,
    MatchingDataset,
    SortingDataset,
)
from .utils import strip_html

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Общий хелпер
# ═══════════════════════════════════════════════════════════════

def _find_option_index(
        target: str,
        options: list[str],
        used: set[int],
) -> int | None:
    """Ищет индекс совпадения: сначала точное, потом по регистру."""
    # Точное совпадение
    for j, option in enumerate(options):
        if j not in used and option == target:
            return j

    # Нечёткое (регистр)
    lower_target = target.lower()
    for j, option in enumerate(options):
        if j not in used and option.lower() == lower_target:
            return j

    return None

# ═══════════════════════════════════════════════════════════════
#  Matching
# ═══════════════════════════════════════════════════════════════

def _build_correct_mapping(pairs: list[SourcePair]) -> dict[str, str] | None:
    """source.pairs → {term: definition}.

    Возвращает None если данные неполные или пустые.
    """
    if not pairs:
        return None

    mapping: dict[str, str] = {}
    for pair in pairs:
        first = strip_html(pair.first)
        second = strip_html(pair.second)
        if not first or not second:
            return None
        mapping[first] = second

    return mapping


def _parse_matching_dataset(attempt: AttemptData) -> tuple[list[str], list[str]] | None:
    """dataset → (terms, options) через Pydantic-валидацию.

    Возвращает None если dataset не соответствует MatchingDataset.
    """
    try:
        ds = MatchingDataset.model_validate(attempt.dataset)
    except ValidationError:
        return None

    if not ds.pairs or not ds.options:
        return None

    terms = [strip_html(p.first) for p in ds.pairs]
    options = [strip_html(opt) for opt in ds.options]

    if not all(terms) or not all(options):
        return None

    return terms, options


def _match_terms_to_options(
        terms: list[str],
        options: list[str],
        correct: dict[str, str],
) -> list[int] | None:
    """Сопоставляет каждый термин с опцией через маппинг.

    Возвращает ordering или None если не все термины найдены.
    """
    ordering: list[int] = []
    used: set[int] = set()

    for term in terms:
        expected = correct.get(term)
        if expected is None:
            return None

        found = _find_option_index(expected, options, used)
        if found is not None:
            ordering.append(found)
            used.add(found)
        else:
            return None

    return ordering


def try_solve_matching(step: StepData, attempt: AttemptData) -> list[int] | None:
    """Координатор: решает matching без AI.

    Возвращает ordering или None если программное решение невозможно.
    """
    correct = _build_correct_mapping(step.source.pairs)
    if correct is None:
        logger.debug("Matching: source.pairs пусты или неполны → AI.")
        return None

    parsed = _parse_matching_dataset(attempt)
    if parsed is None:
        logger.debug("Matching: dataset невалиден → AI.")
        return None

    terms, options = parsed
    result = _match_terms_to_options(terms, options, correct)

    if result is not None:
        logger.info("Matching решён программно: %s", result)
    else:
        logger.debug("Matching: не удалось сопоставить все термины → AI.")

    return result

# ═══════════════════════════════════════════════════════════════
#  Sorting
# ═══════════════════════════════════════════════════════════════

def _parse_sorting_dataset(attempt: AttemptData) -> list[str] | None:
    """dataset → shuffled options через Pydantic-валидацию."""
    try:
        ds = SortingDataset.model_validate(attempt.dataset)
    except ValidationError:
        return None

    if not ds.options:
        return None

    return [strip_html(opt) for opt in ds.options]


def _build_sorting_order(
        correct_order: list[str],
        shuffled: list[str],
) -> list[int] | None:
    """Находит перестановку correct_order → shuffled."""
    if len(correct_order) != len(shuffled):
        return None

    ordering: list[int] = []
    used: set[int] = set()

    for item in correct_order:
        found = _find_option_index(item, shuffled, used)
        if found is not None:
            ordering.append(found)
            used.add(found)
        else:
            return None

    return ordering


def try_solve_sorting(step: StepData, attempt: AttemptData) -> list[int] | None:
    """Координатор: решает sorting без AI."""
    src_opts = step.source.options
    if not src_opts:
        logger.debug("Sorting: source.options пусты → AI.")
        return None

    correct_order = [strip_html(str(opt)) for opt in src_opts]

    shuffled = _parse_sorting_dataset(attempt)
    if shuffled is None:
        logger.debug("Sorting: dataset невалиден → AI.")
        return None

    result = _build_sorting_order(correct_order, shuffled)

    if result is not None:
        logger.info("Sorting решён программно: %s", result)
    else:
        logger.debug("Sorting: не удалось построить порядок → AI.")

    return result
