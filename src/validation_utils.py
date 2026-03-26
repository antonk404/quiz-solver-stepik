from collections.abc import Sequence


def validate_selected_indices(
    selected_indices: Sequence[int],
    options_count: int,
    *,
    exc_type: type[Exception] = ValueError,
) -> None:
    """Проверяет выбранные индексы для задач с вариантами ответа.

    Проверка используется в двух слоях:
    - AI-слой: валидация ответа модели;
    - DOM-слой: защита перед кликами по элементам страницы.
    """
    if not selected_indices:
        raise exc_type("Список индексов для ответа пуст.")

    unique_count = len(set(selected_indices))
    if unique_count != len(selected_indices):
        raise exc_type("Список индексов содержит дубли.")

    min_index = min(selected_indices)
    if min_index < 0:
        raise exc_type("Список индексов содержит отрицательное значение.")

    max_index = options_count - 1
    for index in selected_indices:
        if index > max_index:
            raise exc_type(
                f"Индекс ответа выходит за пределы допустимого диапазона: {index}. "
                f"Ожидалось значение от 0 до {max_index}."
            )


def validate_ordered_indices(
    ordered_indices: Sequence[int],
    items_count: int,
    *,
    exc_type: type[Exception] = ValueError,
) -> None:
    """Проверяет, что ordered_indices является перестановкой диапазона [0..items_count-1]."""
    if not ordered_indices:
        raise exc_type("Порядок индексов пуст.")

    if len(ordered_indices) != items_count:
        raise exc_type(
            f"Некорректная длина ordered_indices: {len(ordered_indices)}. Ожидалось {items_count}."
        )

    expected = set(range(items_count))
    actual = set(ordered_indices)
    if actual != expected:
        raise exc_type(
            "ordered_indices должен содержать каждый индекс ровно один раз "
            f"в диапазоне от 0 до {items_count - 1}."
        )
