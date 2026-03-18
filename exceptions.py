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


class AIClientRegionUnsupportedError(AIClientResponseError):
    """Ошибка: Gemini API недоступен из текущего региона/локации пользователя."""
    message = "Gemini API недоступен из текущего региона/локации."


class ParserError(AppError):
    """Базовая ошибка при парсинге или взаимодействии с DOM."""
    message = "Произошла ошибка при работе со страницей браузера."


class DOMElementNotFoundError(ParserError):
    """Ошибка: ожидаемый элемент не найден на странице."""
    message = "Не удалось найти необходимый элемент на странице."


class InvalidAnswerIndicesError(ParserError):
    """Ошибка: индексы ответа некорректны для текущего набора вариантов."""
    message = "Переданы некорректные индексы вариантов ответа."