"""Программное решение matching/sorting без AI."""

import logging

from .schemas import (
    StepData,
    AttemptData,
    SourcePair,
)
from .utils import strip_html

logger = logging.getLogger(__name__)


def _find_option_index(
    target: str,
    options: list[str],
    used: set[int],
) -> int | None:
    """Ищет индекс совпадения: сначала точное, потом по регистру."""
    for j, option in enumerate(options):
        if j not in used and option == target:
            return j

    lower_target = target.lower()
    for j, option in enumerate(options):
        if j not in used and option.lower() == lower_target:
            return j

    # Fuzzy: содержание (для случаев с лишними пробелами)
    stripped = target.strip().lower()
    for j, option in enumerate(options):
        if j not in used and option.strip().lower() == stripped:
            return j

    return None


def _build_correct_mapping(
    pairs: list[SourcePair],
) -> dict[str, str] | None:
    """term → definition из source.pairs."""
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


def _parse_matching_dataset(
    attempt: AttemptData,
) -> tuple[list[str], list[str]] | None:
    """Извлекает (terms, options) из dataset.

    Пробует два варианта:
    1. dataset.pairs + dataset.options (старый формат)
    2. dataset.pairs[].first + dataset.pairs[].second (новый формат)
    """
    pairs = attempt.dataset.get("pairs", [])
    if not pairs:
        return None

    terms = [strip_html(str(p.get("first", ""))) for p in pairs]

    # Вариант 1: отдельное поле options
    options_raw = attempt.dataset.get("options", [])
    if options_raw:
        options = [strip_html(str(o)) for o in options_raw]
    else:
        # Вариант 2: second из pairs
        options = [
            strip_html(str(p.get("second", ""))) for p in pairs
        ]

    if not all(terms) or not all(options):
        return None

    return terms, options


def _match_terms_to_options(
    terms: list[str],
    options: list[str],
    correct: dict[str, str],
) -> list[int] | None:
    """Строит ordering по маппингу."""
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


def try_solve_matching(
    step: StepData, attempt: AttemptData,
) -> list[int] | None:
    """Пытается решить matching без AI."""
    correct = _build_correct_mapping(step.source.pairs)
    if correct is None:
        logger.debug("Matching: source.pairs пусты → AI.")
        return None

    parsed = _parse_matching_dataset(attempt)
    if parsed is None:
        logger.debug("Matching: dataset невалиден → AI.")
        return None

    terms, options = parsed
    result = _match_terms_to_options(terms, options, correct)

    if result is not None:
        logger.info(
            "✨ Matching решён программно: %s", result
        )
    else:
        logger.debug(
            "Matching: не удалось сопоставить → AI."
        )

    return result


# ── Sorting ────────────────────────────────────────────────────

def _parse_sorting_dataset(
    attempt: AttemptData,
) -> list[str] | None:
    """dataset → shuffled options."""
    options = attempt.dataset.get("options", [])
    if not options:
        return None

    return [strip_html(str(opt)) for opt in options]


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


def try_solve_sorting(
    step: StepData, attempt: AttemptData,
) -> list[int] | None:
    """Решает sorting без AI."""
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
        logger.info(
            "✨ Sorting решён программно: %s", result
        )
    else:
        logger.debug(
            "Sorting: не удалось построить порядок → AI."
        )

    return result


# ── Choice ─────────────────────────────────────────────────────

def try_solve_choice(
    step: StepData,
) -> list[int] | None:
    """Пытается решить choice без AI.

    Stepik хранит правильные ответы в source.options[].is_correct.
    Не все курсы это возвращают, но многие — да.
    """
    options = step.source.options
    if not options:
        return None

    # Проверяем есть ли поле is_correct
    selected: list[int] = []
    has_correct_field = False

    for i, opt in enumerate(options):
        if isinstance(opt, dict) and "is_correct" in opt:
            has_correct_field = True
            if opt["is_correct"]:
                selected.append(i)

    if not has_correct_field:
        logger.debug("Choice: source.options без is_correct → AI.")
        return None

    if not selected:
        logger.debug("Choice: ни один вариант не is_correct → AI.")
        return None

    logger.info(
        "✨ Choice решён программно: indices=%s", selected
    )
    return selected
