from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


class ChoiceResponse(BaseModel):
    type: Literal["choice"] = "choice"
    selected_indices: list[int] = Field(description="Список индексов правильных ответов (0-based)")
    reasoning: str


class StringResponse(BaseModel):
    type: Literal["string"] = "string"
    answer: str
    reasoning: str


class OrderingResponse(BaseModel):
    type: Literal["ordering"] = "ordering"
    ordered_indices: list[int] = Field(description="Новый порядок индексов элементов")
    reasoning: str


class ChoiceTaskData(BaseModel):
    """Модель данных, извлеченных со страницы для задачи типа Choice."""
    question: str = Field(description="Текст запроса")
    options: list[str] = Field(
        description="Список вариантов",
        validation_alias=AliasChoices("options", "option"),
    )


class OrderingTaskData(BaseModel):
    """Данные для задачи на сопоставление/упорядочивание."""
    question: str
    left_items: list[str]
    right_items: list[str]
