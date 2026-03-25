"""Pydantic-модели для Stepik API: ответы сервера + бизнес-объекты."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════
#  API Response Models — парсинг JSON от Stepik
# ═══════════════════════════════════════════════════════════════

# ── Steps ───────────────────────────────────────────────────────

class SourcePair(BaseModel):
    """Правильная пара term↔definition в source.pairs."""
    first: str = ""
    second: str = ""


class BlockSource(BaseModel):
    """Блок source внутри step.block — содержит правильные ответы."""
    model_config = ConfigDict(extra="allow")

    options: list[Any] = Field(default_factory=list)
    is_multiple_choice: bool = False
    pairs: list[SourcePair] = Field(default_factory=list)


class StepBlock(BaseModel):
    """step.block — тип задания + HTML-текст + source."""
    name: str = "unknown"
    text: str = ""
    source: BlockSource = Field(default_factory=BlockSource)


class StepRaw(BaseModel):
    """Сырой шаг из GET /api/steps/{id}."""
    model_config = ConfigDict(extra="allow")

    id: int
    lesson: int = 0
    position: int = 0
    block: StepBlock = Field(default_factory=StepBlock)


class StepsResponse(BaseModel):
    steps: list[StepRaw]


# ── Attempts ────────────────────────────────────────────────────

class AttemptRaw(BaseModel):
    """Сырая попытка из GET/POST /api/attempts."""
    model_config = ConfigDict(extra="allow")

    id: int
    step: int = 0
    dataset: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class AttemptsResponse(BaseModel):
    attempts: list[AttemptRaw]


# ── Submissions ─────────────────────────────────────────────────

class SubmissionRaw(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    status: str = "evaluation"


class SubmissionsResponse(BaseModel):
    submissions: list[SubmissionRaw]


# ── Lessons / Courses / Sections / Units ────────────────────────

class LessonRaw(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    steps: list[int] = Field(default_factory=list)


class LessonsResponse(BaseModel):
    lessons: list[LessonRaw]


class CourseRaw(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    sections: list[int] = Field(default_factory=list)


class CoursesResponse(BaseModel):
    courses: list[CourseRaw]


class SectionRaw(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    units: list[int] = Field(default_factory=list)


class SectionsResponse(BaseModel):
    sections: list[SectionRaw]


class UnitRaw(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    lesson: int = 0


class UnitsResponse(BaseModel):
    units: list[UnitRaw]


# ═══════════════════════════════════════════════════════════════
#  Business Models — используются внутри проекта
# ═══════════════════════════════════════════════════════════════

class StepData(BaseModel):
    """Обработанные данные шага."""
    step_id: int
    lesson_id: int
    position: int
    block_type: str
    question_html: str
    question_text: str
    is_multiple_choice: bool = False
    source: BlockSource = Field(default_factory=BlockSource)


class AttemptData(BaseModel):
    """Обработанные данные попытки."""
    attempt_id: int
    step_id: int
    dataset: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class ParsedStepURL(BaseModel):
    """Результат парсинга URL шага."""
    lesson_id: int
    step_position: int


# ═══════════════════════════════════════════════════════════════
#  Typed Datasets — для солверов
# ═══════════════════════════════════════════════════════════════

class DatasetPair(BaseModel):
    """Элемент левого столбца в dataset.pairs."""
    first: str = ""


class MatchingDataset(BaseModel):
    """Типизированный dataset для matching-задач."""
    pairs: list[DatasetPair] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)


class SortingDataset(BaseModel):
    """Типизированный dataset для sorting-задач."""
    options: list[str] = Field(default_factory=list)
