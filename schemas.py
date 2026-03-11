from pydantic import BaseModel, Field
from typing import Literal, List, Union


# Модели для ответов Gemini
class ChoiceResponse(BaseModel):
    type: Literal["choice"]
    selected_indices: List[int] = Field(description="Список индексов правильных ответов (0-based)")
    reasoning: str


class StringResponse(BaseModel):
    type: Literal["string"]
    answer: str
    reasoning: str


class OrderingResponse(BaseModel):
    type: Literal["ordering"]
    ordered_indices: List[int] = Field(description="Новый порядок индексов элементов")
    reasoning: str


class TableResponse(BaseModel):
    type: Literal["table"]
    # Словарь: ключ - строка (строка таблицы), значение - столбец (столбец таблицы)
    mapping: dict[str, str]
    reasoning: str


# Главный тип для валидации ответа от Gemini
TaskResponse = Union[ChoiceResponse, StringResponse, OrderingResponse, TableResponse]


class TaskCache(BaseModel):
    question_hash: str
    last_response: TaskResponse
    is_correct: bool = False

