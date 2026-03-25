"""Исключения Stepik API — типизированные по причине ошибки."""


class StepikAPIError(Exception):
    """Базовая ошибка API Stepik."""

    default_message = "Произошла ошибка в API Stepik."

    def __init__(self, message: str | None) -> None:
        super().__init__(message or self.default_message)


class StepikAuthError(StepikAPIError):
    """Сессия истекла / нет авторизации (401, 403)."""
    default_message = "Сессия истекла / нет авторизации."


class StepikNotFoundError(StepikAPIError):
    """Ресурс не найден (404)."""
    default_message = "Ресурс не найден."


class StepikAPITransientError(StepikAPIError):
    """Транзиентная ошибка (429, 5xx) — стоит повторить."""
    default_message = "Транзиентная ошибка сервера."

    def __init__(self, status: int, text: str = "") -> None:
        self.status = status
        message = f"HTTP {status}: {text}" if text else f"HTTP {status}"
        super().__init__(message)
