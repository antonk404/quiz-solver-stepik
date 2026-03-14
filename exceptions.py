class AppError(Exception):
    """Базовая ошибка приложения. От нее наследуются все остальные."""
    message: str = "Произошла непредвиденная ошибка."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class AIClientError(AppError):
    """Базовая ошибка для операций с клиентским ИИ."""
    message = "Произошла ошибка при работе с клиентом ИИ."


class AIClientConfigError(AIClientError):
    """Ошибка конфигурации клиента ИИ."""
    message = "Некорректная конфигурация клиента ИИ."


class AIClientInputError(AIClientError):
    """Ошибка входных данных задачи для клиента ИИ."""
    message = "Входные данные для задачи ИИ некорректны."


class AIClientResponseError(AIClientError):
    """Ошибка ответа модели: пустой, некорректный или невалидный по смыслу."""
    message = "Ответ модели некорректен или не прошел проверку."
