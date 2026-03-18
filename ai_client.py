import logging
from textwrap import dedent

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from pydantic import ValidationError
from tenacity import RetryError

from config import settings
from exceptions import (
    AIClientConfigError,
    AIClientInputError,
    AIClientRegionUnsupportedError,
    AIClientResponseError,
)
from schemas import ChoiceResponse, OrderingResponse, StringResponse
from retry_utils import retry_on_api
from validation_utils import validate_ordered_indices, validate_selected_indices

logger = logging.getLogger(__name__)


class AIClient:
    """Клиент для задач типа Choice, Ordering и String через SDK Gemini (google-genai)."""

    def __init__(
            self,
            client: genai.Client | None = None,
            api_key: str | None = None,
            model_name: str | None = None,
            temperature: float = 0.1,
            max_reasks: int = 2,
    ):
        self.temperature = temperature
        self.max_reasks = max_reasks

        resolved_models = self._parse_model_candidates(model_name or settings.gemini_model)
        if not resolved_models:
            raise AIClientConfigError("Gemini model name is empty.")

        self.model_candidates = resolved_models
        self.model_name = resolved_models[0]
        self._region_unsupported = False

        if self.max_reasks < 0:
            raise AIClientConfigError("Параметр max_reasks не может быть отрицательным.")

        # Dependency injection: принимаем готового клиента
        if client is not None:
            self.client = client
        else:
            resolved_api_key = (api_key or settings.gemini_api_key).strip()
            if not resolved_api_key:
                raise AIClientConfigError("Gemini API key is empty.")

            # Инициализация клиента
            self.client = genai.Client(api_key=resolved_api_key)

        # Отключение фильтров безопасности
        self.safety_settings = [
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
        ]

    @staticmethod
    def _parse_model_candidates(raw_models: str) -> list[str]:
        """Парсит список моделей из строки (поддержка ',', ';' и переносов)."""
        chunks = raw_models.replace(";", ",").replace("\n", ",").split(",")
        seen: set[str] = set()
        result: list[str] = []
        for chunk in chunks:
            model = chunk.strip()
            if not model or model in seen:
                continue
            seen.add(model)
            result.append(model)
        return result

    @staticmethod
    def _validate_inputs(question: str, options: list[str]) -> None:
        """Проверяет вход до обращения к модели."""
        if not question or not question.strip():
            raise AIClientInputError("Вопрос должен представлять собой непустую строку.")
        if not options:
            raise AIClientInputError("Варианты не должны быть пустыми.")
        if any(not option or not option.strip() for option in options):
            raise AIClientInputError("Каждый параметр должен быть непустой строкой.")

    @staticmethod
    def _validate_selected_indices(selected_indices: list[int], options_count: int) -> None:
        """Проверяет бизнес-инварианты ответа модели."""
        validate_selected_indices(
            selected_indices,
            options_count,
            exc_type=AIClientResponseError,
        )

    @staticmethod
    def _validate_ordered_indices(ordered_indices: list[int], items_count: int) -> None:
        """Проверяет бизнес-инварианты для задач на упорядочивание."""
        validate_ordered_indices(
            ordered_indices,
            items_count,
            exc_type=AIClientResponseError,
        )

    @staticmethod
    def _build_reask_block(validation_feedback: str | None) -> str:
        """Универсальный генератор блока переспроса при ошибках валидации."""
        if not validation_feedback:
            return ""
        return dedent(
            f"""
            ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ ОТКЛОНЕН:
            {validation_feedback}

            ИСПРАВЬ ОШИБКУ И ВЕРНИ ТОЛЬКО КОРРЕКТНЫЙ JSON ПО СХЕМЕ.
            """
        )

    @classmethod
    def _build_choice_prompt(
            cls,
            question: str,
            options: list[str],
            validation_feedback: str | None = None,
    ) -> str:
        """Собирает prompt для задачи выбора вариантов."""
        options_text = "\n".join(f"[{i}] {option.strip()}" for i, option in enumerate(options))
        reask_block = cls._build_reask_block(validation_feedback)

        return dedent(
            f"""
            Ты - эксперт, помогающий решать тесты.
            Проанализируй вопрос и выбери правильные варианты ответов.

            ВОПРОС:
            {question.strip()}

            ВАРИАНТЫ ОТВЕТОВ:
            {options_text}

            Верни ответ СТРОГО в формате JSON.
            {reask_block}
            """
        ).strip()

    @classmethod
    def _build_ordering_prompt(
            cls,
            question: str,
            left_items: list[str],
            right_items: list[str],
            validation_feedback: str | None = None,
    ) -> str:
        """Собирает prompt для задач на сопоставление/упорядочивание."""
        left_text = "\n".join(f"[{i}] {item.strip()}" for i, item in enumerate(left_items))
        right_text = "\n".join(f"[{i}] {item.strip()}" for i, item in enumerate(right_items))
        reask_block = cls._build_reask_block(validation_feedback)

        return dedent(
            f"""
            Ты - эксперт, помогающий решать учебные задания.
            Нужно сопоставить элементы двух списков: для каждого элемента слева выбери соответствующий элемент справа.

            ВОПРОС:
            {question.strip()}

            ЛЕВЫЙ СПИСОК (целевой порядок):
            {left_text}

            ПРАВЫЙ СПИСОК (текущий порядок):
            {right_text}

            Верни ordered_indices: это индексы ПРАВОГО списка в том порядке, в котором они должны стоять,
            чтобы соответствовать левому списку сверху вниз.

            Верни ответ СТРОГО в формате JSON.
            {reask_block}
            """
        ).strip()

    @classmethod
    def _build_string_prompt(cls, question: str, validation_feedback: str | None = None) -> str:
        """Собирает prompt для задач со строковым ответом."""
        reask_block = cls._build_reask_block(validation_feedback)

        return dedent(
            f"""
            Ты - эксперт, помогающий решать учебные задания.
            Дай краткий и точный ответ на вопрос:
            "{question.strip()}"

            Верни ответ СТРОГО в формате JSON.
            {reask_block}
            """
        ).strip()

    @staticmethod
    def _format_reask_reason(exc: Exception) -> str:
        """Формирует компактную причину переспроса."""
        if isinstance(exc, ValidationError):
            errors = exc.errors(include_url=False)
            if errors:
                first_error = errors[0]
                path = ".".join(str(part) for part in first_error.get("loc", []))
                message = first_error.get("msg", "неизвестная ошибка валидации")
                if path:
                    return f"Ошибка структуры JSON в поле '{path}': {message}."
                return f"Ошибка структуры JSON: {message}."
            return "Ошибка структуры JSON: ответ не соответствует ожидаемой схеме."

        return str(exc) or "Ответ не прошел проверку."

    @staticmethod
    def _build_api_error(exc: Exception) -> AIClientResponseError:
        """Преобразует ошибки SDK/ретраев в понятные ошибки домена."""
        error_text = str(exc)
        upper = error_text.upper()

        if "FAILED_PRECONDITION" in upper and "USER LOCATION IS NOT SUPPORTED" in upper:
            return AIClientRegionUnsupportedError(
                "Gemini API недоступен для текущей локации пользователя "
                "(FAILED_PRECONDITION: User location is not supported for the API use)."
            )

        if "NOT_FOUND" in upper or "404" in upper:
            return AIClientResponseError(
                "Указанная модель Gemini недоступна для generateContent. "
                "Проверьте GEMINI_MODEL."
            )

        if "RESOURCE_EXHAUSTED" in upper or "429" in upper:
            if "GENERATEREQUESTSPERDAYPERPROJECTPERMODEL-FREETIER" in upper or "PERDAY" in upper:
                return AIClientResponseError(
                    "Достигнут суточный лимит Gemini API (free tier). "
                    "Новые запросы появятся после сброса дневной квоты."
                )
            if "GENERATEREQUESTSPERMINUTEPERPROJECTPERMODEL-FREETIER" in upper or "PERMINUTE" in upper:
                return AIClientResponseError(
                    "Достигнут минутный лимит Gemini API. Подождите немного."
                )
            if "LIMIT: 0" in upper:
                return AIClientResponseError(
                    "Квота Gemini для текущего проекта равна 0. Включите billing."
                )
            return AIClientResponseError("Превышена квота Gemini API.")

        if "UNAVAILABLE" in upper or "503" in upper:
            return AIClientResponseError(
                "Gemini временно недоступен из-за высокой нагрузки (503 UNAVAILABLE). "
                "Повторите попытку позже или увеличьте API_RETRY_ATTEMPTS."
            )

        return AIClientResponseError(f"Ошибка Gemini API: {error_text}")

    @staticmethod
    def _is_daily_quota_error(exc: Exception) -> bool:
        upper = str(exc).upper()
        return "GENERATEREQUESTSPERDAYPERPROJECTPERMODEL-FREETIER" in upper or "PERDAY" in upper

    @retry_on_api
    async def _request_json(self, prompt: str, model_name: str, schema: type) -> str:
        """Универсальный вызов к API Gemini. Возвращает сырой JSON-текст по заданной схеме."""
        response = await self.client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=self.temperature,
                safety_settings=self.safety_settings,
            )
        )

        raw_text = (response.text or "").strip()
        if not raw_text:
            raise AIClientResponseError("Модель Gemini вернула пустое тело ответа.")

        return raw_text

    async def solve_choice_task(self, question: str, options: list[str]) -> ChoiceResponse:
        """Решает задачу типа Choice и возвращает строго валидированный результат."""
        if self._region_unsupported:
            raise AIClientRegionUnsupportedError()

        self._validate_inputs(question, options)
        logger.info(
            "Отправка задачи 'choice' в Gemini: вариантов=%s, max_reasks=%s, моделей=%s",
            len(options),
            self.max_reasks,
            len(self.model_candidates),
        )

        total_attempts = self.max_reasks + 1
        total_models = len(self.model_candidates)

        for model_pos, model_name in enumerate(self.model_candidates, start=1):
            validation_feedback: str | None = None
            logger.info("Используем Gemini модель %s/%s: %s", model_pos, total_models, model_name)

            for attempt in range(1, total_attempts + 1):
                prompt = self._build_choice_prompt(question, options, validation_feedback=validation_feedback)
                try:
                    raw_text = await self._request_json(prompt, model_name=model_name, schema=ChoiceResponse)
                except RetryError as exc:
                    base_exc = exc.last_attempt.exception() if exc.last_attempt else exc
                    if self._is_daily_quota_error(base_exc) and model_pos < total_models:
                        logger.warning("Суточная квота модели '%s' исчерпана. Переключаемся.", model_name)
                        break
                    api_error = self._build_api_error(base_exc)
                    if isinstance(api_error, AIClientRegionUnsupportedError):
                        self._region_unsupported = True
                    raise api_error from exc
                except ClientError as exc:
                    if self._is_daily_quota_error(exc) and model_pos < total_models:
                        logger.warning("Суточная квота модели '%s' исчерпана. Переключаемся.", model_name)
                        break
                    api_error = self._build_api_error(exc)
                    if isinstance(api_error, AIClientRegionUnsupportedError):
                        self._region_unsupported = True
                    raise api_error from exc

                try:
                    result = ChoiceResponse.model_validate_json(raw_text)
                    self._validate_selected_indices(result.selected_indices, len(options))

                    logger.info("Gemini выбрала индексы: %s (попытка %s)", result.selected_indices, attempt)
                    logger.debug("Краткое обоснование: %s", result.reasoning[:200])
                    self.model_name = model_name
                    return result

                except (ValidationError, AIClientResponseError) as exc:
                    validation_feedback = self._format_reask_reason(exc)
                    logger.warning("Ответ не прошел проверку на попытке %s: %s", attempt, validation_feedback)
                    logger.debug("Сырой ответ: %s", raw_text[:500])

                    if attempt == total_attempts:
                        raise AIClientResponseError("Не удалось получить корректный ответ после всех попыток.") from exc

        raise AIClientResponseError("Все доступные Gemini модели исчерпали дневную квоту или временно недоступны.")

    async def solve_ordering_task(
            self,
            question: str,
            left_items: list[str],
            right_items: list[str],
    ) -> OrderingResponse:
        """Решает задачу сопоставления/упорядочивания (по двум спискам)."""
        if self._region_unsupported:
            raise AIClientRegionUnsupportedError()

        if not question or not question.strip():
            raise AIClientInputError("Вопрос должен представлять собой непустую строку.")
        if not left_items or not right_items or len(left_items) != len(right_items):
            raise AIClientInputError("Списки элементов должны быть непустыми и одинаковой длины.")

        total_attempts = self.max_reasks + 1
        total_models = len(self.model_candidates)
        logger.info(
            "Отправка задачи 'ordering' в Gemini: left=%s, right=%s, max_reasks=%s, моделей=%s",
            len(left_items), len(right_items), self.max_reasks, total_models
        )

        for model_pos, model_name in enumerate(self.model_candidates, start=1):
            validation_feedback: str | None = None
            logger.info("Используем Gemini модель %s/%s: %s", model_pos, total_models, model_name)

            for attempt in range(1, total_attempts + 1):
                prompt = self._build_ordering_prompt(
                    question, left_items, right_items, validation_feedback=validation_feedback
                )
                try:
                    raw_text = await self._request_json(prompt, model_name=model_name, schema=OrderingResponse)
                except RetryError as exc:
                    base_exc = exc.last_attempt.exception() if exc.last_attempt else exc
                    if self._is_daily_quota_error(base_exc) and model_pos < total_models:
                        logger.warning("Суточная квота модели '%s' исчерпана. Переключаемся.", model_name)
                        break
                    api_error = self._build_api_error(base_exc)
                    if isinstance(api_error, AIClientRegionUnsupportedError):
                        self._region_unsupported = True
                    raise api_error from exc
                except ClientError as exc:
                    if self._is_daily_quota_error(exc) and model_pos < total_models:
                        logger.warning("Суточная квота модели '%s' исчерпана. Переключаемся.", model_name)
                        break
                    api_error = self._build_api_error(exc)
                    if isinstance(api_error, AIClientRegionUnsupportedError):
                        self._region_unsupported = True
                    raise api_error from exc

                try:
                    result = OrderingResponse.model_validate_json(raw_text)
                    self._validate_ordered_indices(result.ordered_indices, len(right_items))

                    logger.info("Gemini вернула порядок: %s (попытка %s)", result.ordered_indices, attempt)
                    self.model_name = model_name
                    return result
                except (ValidationError, AIClientResponseError) as exc:
                    validation_feedback = self._format_reask_reason(exc)
                    logger.warning("Ordering-ответ не прошел проверку на попытке %s: %s", attempt, validation_feedback)

                    if attempt == total_attempts:
                        raise AIClientResponseError("Не удалось получить корректный ordering-ответ.") from exc

        raise AIClientResponseError("Все доступные Gemini модели исчерпали дневную квоту.")

    async def solve_string_task(self, question: str) -> StringResponse:
        """Решает задачу типа String (вписать текст)."""
        if self._region_unsupported:
            raise AIClientRegionUnsupportedError()

        if not question or not question.strip():
            raise AIClientInputError("Вопрос должен представлять собой непустую строку.")

        total_attempts = self.max_reasks + 1
        total_models = len(self.model_candidates)
        logger.info("Отправка задачи 'string' в Gemini: max_reasks=%s", self.max_reasks)

        for model_pos, model_name in enumerate(self.model_candidates, start=1):
            logger.info("Используем Gemini модель %s/%s: %s", model_pos, total_models, model_name)
            validation_feedback: str | None = None

            for attempt in range(1, total_attempts + 1):
                prompt = self._build_string_prompt(question, validation_feedback=validation_feedback)
                try:
                    raw_text = await self._request_json(prompt, model_name=model_name, schema=StringResponse)
                except RetryError as exc:
                    base_exc = exc.last_attempt.exception() if exc.last_attempt else exc
                    if self._is_daily_quota_error(base_exc) and model_pos < total_models:
                        logger.warning("Суточная квота модели '%s' исчерпана. Переключаемся.", model_name)
                        break
                    api_error = self._build_api_error(base_exc)
                    if isinstance(api_error, AIClientRegionUnsupportedError):
                        self._region_unsupported = True
                    raise api_error from exc
                except ClientError as exc:
                    if self._is_daily_quota_error(exc) and model_pos < total_models:
                        logger.warning("Суточная квота модели '%s' исчерпана. Переключаемся.", model_name)
                        break
                    api_error = self._build_api_error(exc)
                    if isinstance(api_error, AIClientRegionUnsupportedError):
                        self._region_unsupported = True
                    raise api_error from exc

                try:
                    result = StringResponse.model_validate_json(raw_text)
                    if not result.answer or not result.answer.strip():
                        raise AIClientResponseError("Модель вернула пустой текстовый answer.")

                    self.model_name = model_name
                    logger.info("Gemini предложил string-ответ (попытка %s).", attempt)
                    return result
                except (ValidationError, AIClientResponseError) as exc:
                    validation_feedback = self._format_reask_reason(exc)
                    logger.warning("String-ответ не прошел проверку на попытке %s: %s", attempt, validation_feedback)

                    if attempt == total_attempts:
                        raise AIClientResponseError("Не удалось получить корректный string-ответ.") from exc

        raise AIClientResponseError("Все доступные Gemini модели исчерпали дневную квоту.")
