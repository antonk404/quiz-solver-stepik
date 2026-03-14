import logging
from textwrap import dedent

import google.generativeai as genai
from pydantic import ValidationError

from config import settings
from exceptions import AIClientConfigError, AIClientInputError, AIClientResponseError
from schemas import ChoiceResponse
from retry_utils import retry_on_api


logger = logging.getLogger(__name__)


class AIClient:
    """Клиент для задач типа Choice через Gemini.

    Поток обработки такой:
    1) Проверяем входные данные (fail-fast), чтобы не тратить API-вызов на заведомо плохой запрос.
    2) Строим prompt c явным JSON-контрактом.
    3) Делаем запрос к Gemini (только этот шаг обернут retry-политикой),
       указывая response_schema для структурной гарантии формата.
    4) Валидируем JSON-структуру через Pydantic.
    5) Валидируем доменные ограничения (индексы должны соответствовать options).
    6) Если валидация не прошла, запускаем Re-Ask с короткой причиной ошибки.

    Такое разделение позволяет не ретраить ошибки бизнес-валидации и упрощает тестирование.
    """

    def __init__(
        self,
        model: genai.GenerativeModel | None = None,
        api_key: str | None = None,
        model_name: str = "gemini-1.5-flash",
        temperature: float = 0.1,
        max_reasks: int = 2,
    ):
        # Temperature хранится на уровне экземпляра, чтобы легко переопределять
        # поведение генерации в тестах и в разных сценариях запуска.
        self.temperature = temperature
        self.max_reasks = max_reasks

        if self.max_reasks < 0:
            raise AIClientConfigError("Параметр max_reasks не может быть отрицательным.")

        if model is not None:
            # Dependency injection: если модель передана снаружи, используем ее как есть.
            # Это убирает скрытые сайд-эффекты и делает класс удобным для unit-тестов.
            self.model = model
            return

        # Поддерживаем оба сценария: явный api_key в конструкторе и ключ из настроек.
        # strip() дополнительно страхует от случайных пробелов в .env.
        resolved_api_key = (api_key or settings.gemini_api_key).strip()
        if not resolved_api_key:
            raise AIClientConfigError

        # configure() задает ключ для SDK в явной форме.
        # Так код более прозрачен, чем присваивание в genai.api_key.
        genai.configure(api_key=resolved_api_key)
        self.model = genai.GenerativeModel(model_name)

    @staticmethod
    def _validate_inputs(question: str, options: list[str]) -> None:
        """Проверяет вход до обращения к модели.

        Мы специально делаем fail-fast в локальном коде:
        - экономим API-квоту,
        - получаем понятные ошибки для вызывающей стороны,
        - не запускаем retry-механику там, где она не нужна.
        """
        # Если вопроса нет или он состоит только из пробелов
        if not question or not question.strip():
            raise AIClientInputError("Вопрос должен представлять собой непустую строку.")
        # Если список вариантов пуст (например, парсер на сайте сломался)
        if not options:
            raise AIClientInputError("Варианты не должны быть пустыми.")
        # Проверяем генератором, нет ли пустых строк внутри массива вариантов
        if any(not option or not option.strip() for option in options):
            raise AIClientInputError("Каждый параметр должен быть непустой строкой.")

    @staticmethod
    def _validate_selected_indices(selected_indices: list[int], options_count: int) -> None:
        """Проверяет бизнес-инварианты ответа модели.

        Pydantic подтверждает только форму данных (list[int]), но не смысл:
        индекс может быть вне диапазона options или повторяться.
        Здесь мы валидируем именно доменные правила.
        """
        # Модель вернула пустой массив, хотя ответ должен быть
        if not selected_indices:
            raise AIClientResponseError("Модель вернула пустые значения selected_indices.")

        # Проверка на дубликаты путем сравнения длины списка и длины множества (set)
        unique_count = len(set(selected_indices))
        if unique_count != len(selected_indices):
            raise AIClientResponseError("Модель вернула повторяющиеся индексы.")

        # Вычисляем максимально допустимый индекс (индексация с нуля)
        max_index = options_count - 1

        # Идем по всем ответам ИИ и проверяем, не выдумал ли он несуществующий вариант
        for index in selected_indices:
            if index < 0 or index > max_index:
                raise AIClientResponseError(
                    f"Модель вернула значение индекса, выходящее за пределы допустимого диапазона: {index}. Ожидалось значение от 0 до {max_index}."
                )

    @staticmethod
    def _build_choice_prompt(
        question: str,
        options: list[str],
        validation_feedback: str | None = None,
    ) -> str:
        """Собирает prompt с опциональным блоком Re-Ask."""
        options_text = "\n".join(f"[{i}] {option.strip()}" for i, option in enumerate(options))

        # Переменная для блока критики (заполняется, если это попытка Re-Ask)
        reask_block = ""
        if validation_feedback:
            # dedent убирает табы отступов кода, сохраняя структуру текста
            reask_block = dedent(
                f"""

                ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ ОТКЛОНЕН:
                {validation_feedback}

                ИСПРАВЬ ОШИБКУ И ВЕРНИ ТОЛЬКО КОРРЕКТНЫЙ JSON ПО СХЕМЕ.
                """
            )
        # .strip() в конце убирает лишние пустые строки
        return dedent(
            f"""
            Ты - эксперт, помогающий решать тесты.
            Проанализируй вопрос и выбери правильные варианты ответов (их может быть один или несколько).

            ВОПРОС:
            {question.strip()}

            ВАРИАНТЫ ОТВЕТОВ:
            {options_text}

            Верни ответ СТРОГО в формате JSON. Структура JSON должна быть следующей:
            {{
                "type": "choice",
                "selected_indices": [целые числа, индексы правильных вариантов],
                "reasoning": "краткое обоснование выбора"
            }}
            {reask_block}
            """
        ).strip()

    @staticmethod
    def _format_reask_reason(exc: Exception) -> str:
        """Формирует компактную причину переспроса для следующего запроса к модели."""
        # Если ошибка пришла от Pydantic (нарушена структура JSON)
        if isinstance(exc, ValidationError):
            # Получаем список ошибок (без лишних URL-ссылок на доку pydantic)
            errors = exc.errors(include_url=False)
            if errors:
                first_error = errors[0]
                # Собираем путь к проблемному полю (например, 'selected_indices.0')
                path = ".".join(str(part) for part in first_error.get("loc", []))
                message = first_error.get("msg", "неизвестная ошибка валидации")

                # Если путь есть, указываем ИИ конкретное поле
                if path:
                    return f"Ошибка структуры JSON в поле '{path}': {message}."
                return f"Ошибка структуры JSON: {message}."
            return "Ошибка структуры JSON: ответ не соответствует ожидаемой схеме."

        # Если это наша кастомная ошибка (например, выход за границы массива)
        # str(exc) вернет текст, который мы передали в raise AIClientResponseError(...)
        return str(exc) or "Ответ не прошел проверку."

    # Декоратор из tenacity: делает повторы при обрыве сети или ошибках API (500, 429)
    @retry_on_api
    async def _request_choice_json(self, prompt: str) -> str:
        """Делает вызов Gemini и возвращает сырой JSON-текст.

        Важно: retry стоит именно здесь, чтобы повторять только сетевой/API-этап.
        Ошибки парсинга и бизнес-валидации ниже не должны ретраиться автоматически.
        """
        response = await self.model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=ChoiceResponse,
                temperature=self.temperature,
            ),
        )

        # Извлекаем текст. Если его нет (например, заблокировано), берем пустую строку
        raw_text = (response.text or "").strip()

        # Если строка пустая, выбрасываем нашу ошибку ответа
        if not raw_text:
            raise AIClientResponseError("Модель Gemini вернула пустое тело ответа.")

        return raw_text

    async def solve_choice_task(self, question: str, options: list[str]) -> ChoiceResponse:
        """Решает задачу типа Choice и возвращает строго валидированный результат.

        Метод не скрывает ошибки под "тихие" значения по умолчанию:
        если формат ответа или индексы некорректны, вызывающая сторона получает
        исключение с единым сообщением и может принять решение (например, retry выше уровнем).
        """
        # Сначала локальная Fail-fast проверка
        self._validate_inputs(question, options)
        logger.info(
            "Отправка задачи типа 'choice' в Gemini: количество вариантов=%s, max_reasks=%s",
            len(options),
            self.max_reasks,
        )

        # Переменная для хранения текста ошибки, которую мы передадим ИИ на следующем круге
        validation_feedback: str | None = None
        # Общее количество попыток = 1 основная + N переспросов
        total_attempts = self.max_reasks + 1

        # Начинаем цикл попыток
        for attempt in range(1, total_attempts + 1):
            # Строим промпт (если attempt > 1, туда подставится validation_feedback)
            prompt = self._build_choice_prompt(question, options, validation_feedback=validation_feedback)
            # Делаем сетевой запрос (внутри сработает retry, если упадет интернет)
            raw_text = await self._request_choice_json(prompt)

            try:
                # Сначала валидация JSON-структуры через Pydantic.
                result = ChoiceResponse.model_validate_json(raw_text)

                # Затем доменная проверка индексов относительно исходных options.
                self._validate_selected_indices(result.selected_indices, len(options))

                logger.info(
                    "Gemini выбрала индексы: %s (успешная попытка %s/%s)",
                    result.selected_indices,
                    attempt,
                    total_attempts,
                )
                logger.debug("Краткое обоснование Gemini (сокращено): %s", result.reasoning[:200])
                return result

            except (ValidationError, AIClientResponseError) as exc:
                # Превращаем ошибку в понятный текст для ИИ
                validation_feedback = self._format_reask_reason(exc)
                logger.warning(
                    "Ответ Gemini не прошел проверку на попытке %s/%s: %s",
                    attempt,
                    total_attempts,
                    validation_feedback,
                )
                logger.debug("Сырой ответ Gemini (сокращен): %s", raw_text[:500])

                # Если это была последняя попытка, пробрасываем ошибку выше, чтобы уронить задачу
                if attempt == total_attempts:
                    raise AIClientResponseError(
                        "Не удалось получить корректный ответ Gemini после всех попыток переспроса."
                    ) from exc

        raise AIClientResponseError("Внутренняя ошибка: цикл попыток завершился без результата.")
