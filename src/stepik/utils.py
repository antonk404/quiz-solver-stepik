"""Утилиты: очистка HTML, парсинг URL."""

import re
import logging
from html import unescape

from .schemas import ParsedStepURL

logger = logging.getLogger(__name__)


def strip_html(html: str) -> str:
    """Конвертирует HTML → чистый текст."""
    if not html:
        logger.debug("strip_html: получена пустая строка.")
        return ""

    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    result = re.sub(r"\s+", " ", text).strip()

    if not result and len(html) > 10:
        logger.warning(
            "strip_html: HTML длиной %d → пустой результат.",
            len(html),
        )

    return result


def parse_step_url(url: str) -> ParsedStepURL | None:
    """``/lesson/12345/step/3`` → ``ParsedStepURL`` или ``None``."""
    m = re.search(r"/lesson/\D*(\d+)/step/(\d+)", url)
    if not m:
        logger.debug("parse_step_url: не распарсить: %s", url)
        return None

    parsed = ParsedStepURL(
        lesson_id=int(m.group(1)),
        step_position=int(m.group(2)),
    )
    logger.debug(
        "parse_step_url: lesson=%d, step=%d",
        parsed.lesson_id, parsed.step_position,
    )
    return parsed


def parse_course_id(url: str) -> int | None:
    """``https://stepik.org/course/6667/syllabus`` → ``6667`` или ``None``."""
    if not url:
        logger.debug("parse_course_id: пустой URL.")
        return None

    m = re.search(r"/course/(\d+)", url)
    if not m:
        logger.warning("parse_course_id: не найден ID курса в URL: %s", url)
        return None

    course_id = int(m.group(1))
    logger.debug("parse_course_id: %d", course_id)
    return course_id
