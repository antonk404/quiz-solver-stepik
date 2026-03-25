"""Формирование reply-словарей для POST /api/submissions.

Каждая функция — один тип задания, одна ответственность.
"""


def build_choice_reply(selected: list[int], total: int) -> dict:
    """Choice: список bool по количеству вариантов."""
    choices = [False] * total
    for i in selected:
        if 0 <= i < total:
            choices[i] = True
    return {"choices": choices}


def build_ordering_reply(ordering: list[int]) -> dict:
    """Matching / Sorting: порядок индексов."""
    return {"ordering": ordering}


def build_string_reply(answer: str) -> dict:
    """String / Free-answer: текстовый ответ."""
    return {"text": answer, "files": []}


def build_number_reply(number: str) -> dict:
    """Number: числовой ответ как строка."""
    return {"number": str(number)}
