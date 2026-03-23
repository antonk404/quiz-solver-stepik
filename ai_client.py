import logging
from textwrap import dedent

from google import genai
from google.genai import types

from pydantic import ValidationError
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
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

# ══════════════════════════════════════════════════════════════════
#  Groq SDK — опциональный импорт
# ══════════════════════════════════════════════════════════════════
try:
    from groq import AsyncGroq
    from groq import (
        RateLimitError as GroqRateLimitError,
        APIStatusError as GroqAPIStatusError,
        APIConnectionError as GroqAPIConnectionError,
        AuthenticationError as GroqAuthenticationError,
    )

    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    AsyncGroq = None  # type: ignore

    # Заглушки, чтобы isinstance() не падал при отсутствии пакета
    class _GroqStub(Exception):
        pass

    GroqRateLimitError = _GroqStub  # type: ignore
    GroqAPIStatusError = _GroqStub  # type: ignore
    GroqAPIConnectionError = _GroqStub  # type: ignore
    GroqAuthenticationError = _GroqStub  # type: ignore


# ── Retry-декоратор для транзиентных ошибок Groq ─────────────────
def _is_groq_transient(exc: BaseException) -> bool:
    """500/502/503/529 и обрывы соединения — стоит повторить."""
    if isinstance(exc, GroqAPIConnectionError):
        return True
    if isinstance(exc, GroqAPIStatusError) and hasattr(exc, "status_code"):
        return getattr(exc, "status_code", 0) in (500, 502, 503, 529)
    return False


if GROQ_AVAILABLE:
    _retry_groq = retry(
        retry=retry_if_exception(_is_groq_transient),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        reraise=True,
    )
else:
    # Пакет не установлен → декоратор-заглушка
    def _retry_groq(fn):  # type: ignore
        return fn


# ══════════════════════════════════════════════════════════════════
#  JSON-схема для Groq (нет native response_schema)
# ══════════════════════════════════════════════════════════════════
_GROQ_SCHEMA_HINTS: dict[str, str] = {
    "ChoiceResponse": (
        "Требуемый JSON:\n"
        '{"type":"choice","selected_indices":[0,2],"reasoning":"обоснование"}\n'
        "selected_indices — список целых чисел: индексы правильных вариантов (с 0).\n"
        "reasoning — краткое обоснование."
    ),
    "OrderingResponse": (
        "Требуемый JSON:\n"
        '{"type":"ordering","ordered_indices":[2,0,1],"reasoning":"обоснование"}\n'
        "ordered_indices — перестановка индексов ПРАВОГО списка, "
        "чтобы элементы встали напротив ЛЕВОГО.\n"
        "reasoning — краткое обоснование."
    ),
    "StringResponse": (
        "Требуемый JSON:\n"
        '{"type":"string","answer":"текст ответа","reasoning":"обоснование"}\n'
        "answer — точный текстовый ответ.\n"
        "reasoning — краткое обоснование."
    ),
}

_GROQ_SYSTEM_MSG = (
    "Ты — эксперт по решению учебных заданий. "
    "ВСЕГДА отвечай ТОЛЬКО валидным JSON строго по указанной схеме. "
    "Никакого текста вне JSON."
)


# ══════════════════════════════════════════════════════════════════
#  AIClient
# ══════════════════════════════════════════════════════════════════
class AIClient:
    """Мульти-провайдерный AI-клиент: Gemini + Groq.

    Режимы (``AI_PROVIDER``):
    * ``gemini`` — только Google Gemini
    * ``groq``   — только Groq (llama-3.3-70b-versatile по умолчанию)
    * ``auto``   — Gemini → Groq (fallback при исчерпании квоты)
    """

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
        if self.max_reasks < 0:
            raise AIClientConfigError("max_reasks не может быть отрицательным.")

        self._region_unsupported = False

        # Провайдер определяем заранее, чтобы корректно инициализировать только нужные клиенты.
        self.ai_provider: str = getattr(
            settings, "ai_provider", "auto"
        ).lower().strip()

        # ── Gemini ──────────────────────────────────────────────
        resolved_models = self._parse_model_candidates(
            model_name or settings.gemini_model
        )
        if not resolved_models:
            raise AIClientConfigError("Gemini model name is empty.")

        self.gemini_model_candidates = resolved_models
        self.model_name = resolved_models[0]

        # Для режима groq-only Gemini не обязателен.
        self.gemini_client: genai.Client | None = None
        should_init_gemini = self.ai_provider in ("gemini", "auto") or client is not None
        if should_init_gemini:
            if client is not None:
                self.gemini_client = client
            else:
                resolved_key = (api_key or settings.gemini_api_key).strip()
                if resolved_key:
                    self.gemini_client = genai.Client(api_key=resolved_key)
                elif self.ai_provider == "gemini":
                    raise AIClientConfigError("Gemini API key is empty.")
                else:
                    logger.info("Gemini не инициализирован: ключ не задан, используем альтернативный провайдер.")

        self.safety_settings = [
            types.SafetySetting(
                category=cat,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            )
            for cat in (
                types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            )
        ]

        # ── Groq ────────────────────────────────────────────────
        self._init_groq()

    # ────────────────────────────────────────────────────────────
    #  Groq init
    # ────────────────────────────────────────────────────────────
    def _init_groq(self) -> None:
        groq_key = getattr(settings, "groq_api_key", "").strip()

        if not groq_key or not GROQ_AVAILABLE:
            self.groq_client = None
            self.groq_model_candidates: list[str] = []
            if groq_key and not GROQ_AVAILABLE:
                logger.warning(
                    "GROQ_API_KEY задан, но пакет 'groq' не установлен. "
                    "Выполните: pip install groq"
                )
            return

        self.groq_client = AsyncGroq(api_key=groq_key)
        raw_model = getattr(
            settings, "groq_model", "llama-3.3-70b-versatile"
        )
        self.groq_model_candidates = self._parse_model_candidates(raw_model)
        logger.info("Groq инициализирован: модели=%s", self.groq_model_candidates)

    # ────────────────────────────────────────────────────────────
    #  Model sequence (Gemini → Groq)
    # ────────────────────────────────────────────────────────────
    def _get_model_sequence(self) -> list[tuple[str, str]]:
        """Упорядоченный список ``(provider, model_name)``."""
        seq: list[tuple[str, str]] = []
        prov = self.ai_provider

        if prov in ("groq", "auto") and self.groq_client is not None:
            for m in self.groq_model_candidates:
                seq.append(("groq", m))

        if prov in ("gemini", "auto") and self.gemini_client is not None:
            for m in self.gemini_model_candidates:
                seq.append(("gemini", m))

        if not seq:
            raise AIClientConfigError(
                "Нет доступных AI-провайдеров. "
                "Задайте GEMINI_API_KEY и/или GROQ_API_KEY."
            )
        return seq

    # ────────────────────────────────────────────────────────────
    #  Утилиты
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def _parse_model_candidates(raw_models: str) -> list[str]:
        chunks = raw_models.replace(";", ",").replace("\n", ",").split(",")
        seen: set[str] = set()
        result: list[str] = []
        for ch in chunks:
            m = ch.strip()
            if m and m not in seen:
                seen.add(m)
                result.append(m)
        return result

    @staticmethod
    def _validate_inputs(question: str, options: list[str]) -> None:
        if not question or not question.strip():
            raise AIClientInputError("Вопрос должен быть непустой строкой.")
        if not options:
            raise AIClientInputError("Варианты не должны быть пустыми.")
        if any(not o or not o.strip() for o in options):
            raise AIClientInputError("Каждый вариант должен быть непустой строкой.")

    @staticmethod
    def _validate_selected_indices(indices: list[int], cnt: int) -> None:
        validate_selected_indices(indices, cnt, exc_type=AIClientResponseError)

    @staticmethod
    def _validate_ordered_indices(indices: list[int], cnt: int) -> None:
        validate_ordered_indices(indices, cnt, exc_type=AIClientResponseError)

    @staticmethod
    def _build_reask_block(feedback: str | None) -> str:
        if not feedback:
            return ""
        return dedent(f"""
            ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ ОТКЛОНЕН:
            {feedback}
            ИСПРАВЬ ОШИБКУ И ВЕРНИ ТОЛЬКО КОРРЕКТНЫЙ JSON ПО СХЕМЕ.
        """)

    @staticmethod
    def _format_reask_reason(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            errors = exc.errors(include_url=False)
            if errors:
                e = errors[0]
                path = ".".join(str(p) for p in e.get("loc", []))
                msg = e.get("msg", "неизвестная ошибка")
                return f"JSON поле '{path}': {msg}." if path else f"JSON: {msg}."
            return "JSON не по схеме."
        return str(exc) or "Ответ не прошел проверку."

    # ────────────────────────────────────────────────────────────
    #  Prompt builders
    # ────────────────────────────────────────────────────────────
    @classmethod
    def _build_choice_prompt(cls, question, options, validation_feedback=None):
        opts_text = "\n".join(f"[{i}] {o.strip()}" for i, o in enumerate(options))
        reask = cls._build_reask_block(validation_feedback)
        return dedent(f"""
            Ты - эксперт, помогающий решать тесты.
            Проанализируй вопрос и выбери правильные варианты ответов.

            ВОПРОС:
            {question.strip()}

            ВАРИАНТЫ ОТВЕТОВ:
            {opts_text}

            Верни ответ СТРОГО в формате JSON.
            {reask}
        """).strip()

    @classmethod
    def _build_ordering_prompt(cls, question, left_items, right_items, validation_feedback=None):
        left_text = "\n".join(f"[{i}] {it.strip()}" for i, it in enumerate(left_items))
        right_text = "\n".join(f"[{i}] {it.strip()}" for i, it in enumerate(right_items))
        reask = cls._build_reask_block(validation_feedback)
        return dedent(f"""
            Ты - эксперт, помогающий решать учебные задания.
            Нужно сопоставить элементы двух списков: для каждого элемента слева
            выбери соответствующий элемент справа.

            ВОПРОС:
            {question.strip()}

            ЛЕВЫЙ СПИСОК (целевой порядок):
            {left_text}

            ПРАВЫЙ СПИСОК (текущий порядок):
            {right_text}

            Верни ordered_indices: это индексы ПРАВОГО списка в том порядке,
            в котором они должны стоять, чтобы соответствовать левому списку
            сверху вниз.

            Верни ответ СТРОГО в формате JSON.
            {reask}
        """).strip()

    @classmethod
    def _build_string_prompt(cls, question, validation_feedback=None):
        reask = cls._build_reask_block(validation_feedback)
        return dedent(f"""
            Ты - эксперт, помогающий решать учебные задания.
            Дай краткий и точный ответ на вопрос:
            "{question.strip()}"

            Верни ответ СТРОГО в формате JSON.
            {reask}
        """).strip()

    # ────────────────────────────────────────────────────────────
    #  Error builders
    # ────────────────────────────────────────────────────────────
    @staticmethod
    def _build_api_error(exc: Exception) -> AIClientResponseError:
        error_text = str(exc)
        upper = error_text.upper()

        if "FAILED_PRECONDITION" in upper and "USER LOCATION IS NOT SUPPORTED" in upper:
            return AIClientRegionUnsupportedError(
                "Gemini API недоступен для текущей локации "
                "(FAILED_PRECONDITION: User location is not supported)."
            )
        if "NOT_FOUND" in upper or "404" in upper:
            return AIClientResponseError(
                "Модель Gemini недоступна. Проверьте GEMINI_MODEL."
            )
        if "RESOURCE_EXHAUSTED" in upper or "429" in upper:
            if "PERDAY" in upper:
                return AIClientResponseError("Суточный лимит Gemini (free tier) исчерпан.")
            if "PERMINUTE" in upper:
                return AIClientResponseError("Минутный лимит Gemini. Подождите.")
            if "LIMIT: 0" in upper:
                return AIClientResponseError("Квота Gemini = 0. Включите billing.")
            return AIClientResponseError("Превышена квота Gemini API.")
        if "UNAVAILABLE" in upper or "503" in upper:
            return AIClientResponseError("Gemini временно недоступен (503).")

        return AIClientResponseError(f"Ошибка Gemini API: {error_text}")

    @staticmethod
    def _build_groq_error(exc: Exception) -> AIClientResponseError:
        if isinstance(exc, GroqAuthenticationError):
            return AIClientConfigError("Неверный GROQ_API_KEY.")
        if isinstance(exc, GroqRateLimitError):
            msg = str(exc)
            if "per day" in msg.lower() or "daily" in msg.lower():
                return AIClientResponseError("Суточный лимит Groq исчерпан.")
            return AIClientResponseError(
                "Превышен лимит Groq API. Подождите или смените модель."
            )
        if isinstance(exc, GroqAPIConnectionError):
            return AIClientResponseError(f"Ошибка соединения с Groq: {exc}")
        if isinstance(exc, GroqAPIStatusError):
            code = getattr(exc, "status_code", "?")
            return AIClientResponseError(f"Groq вернул ошибку {code}: {exc}")
        return AIClientResponseError(f"Ошибка Groq: {exc}")

    @staticmethod
    def _is_daily_quota_error(exc: Exception) -> bool:
        upper = str(exc).upper()
        return (
            "GENERATEREQUESTSPERDAYPERPROJECTPERMODEL-FREETIER" in upper
            or "PERDAY" in upper
        )

    def _is_provider_quota_error(self, exc: Exception, provider: str) -> bool:
        """Квота провайдера исчерпана — стоит переключиться на следующую модель."""
        if provider == "gemini":
            return self._is_daily_quota_error(exc)
        if provider == "groq":
            return isinstance(exc, GroqRateLimitError)
        return False

    def _build_provider_error(
        self, exc: Exception, provider: str
    ) -> AIClientResponseError:
        if provider == "gemini":
            err = self._build_api_error(exc)
            if isinstance(err, AIClientRegionUnsupportedError):
                self._region_unsupported = True
            return err
        if provider == "groq":
            return self._build_groq_error(exc)
        return AIClientResponseError(str(exc))

    # ────────────────────────────────────────────────────────────
    #  API request — Gemini
    # ────────────────────────────────────────────────────────────
    @retry_on_api
    async def _request_json_gemini(
        self, prompt: str, model_name: str, schema: type
    ) -> str:
        if self.gemini_client is None:
            raise AIClientConfigError("Gemini не инициализирован для текущей конфигурации.")
        response = await self.gemini_client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=self.temperature,
                safety_settings=self.safety_settings,
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            raise AIClientResponseError("Gemini вернул пустой ответ.")
        return raw

    # ────────────────────────────────────────────────────────────
    #  API request — Groq
    # ────────────────────────────────────────────────────────────
    @_retry_groq
    async def _request_json_groq(
        self, prompt: str, model_name: str, schema: type
    ) -> str:
        if not self.groq_client:
            raise AIClientConfigError("Groq не инициализирован.")

        hint = _GROQ_SCHEMA_HINTS.get(schema.__name__, "")
        user_content = f"{prompt}\n\n{hint}" if hint else prompt

        response = await self.groq_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _GROQ_SYSTEM_MSG},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=self.temperature,
            max_tokens=1024,
        )

        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise AIClientResponseError("Groq вернул пустой ответ.")
        return raw

    # ────────────────────────────────────────────────────────────
    #  Dispatcher
    # ────────────────────────────────────────────────────────────
    async def _request_json(
        self,
        prompt: str,
        model_name: str,
        schema: type,
        provider: str = "gemini",
    ) -> str:
        if provider == "groq":
            return await self._request_json_groq(prompt, model_name, schema)
        return await self._request_json_gemini(prompt, model_name, schema)

    # ────────────────────────────────────────────────────────────
    #  Универсальный цикл решения
    # ────────────────────────────────────────────────────────────
    async def _solve_loop(
        self,
        task_label: str,
        schema: type,
        prompt_fn,
        validate_fn,
        extract_result_fn,
    ):
        """
        Общий цикл: перебор моделей × reask.

        * ``prompt_fn(feedback) -> str``   — строит prompt
        * ``validate_fn(result)``          — бросает исключение если невалидно
        * ``extract_result_fn(result)``    — вызывается перед return для лога
        """
        model_seq = self._get_model_sequence()
        total = len(model_seq)
        total_attempts = self.max_reasks + 1

        for pos, (provider, model_name) in enumerate(model_seq, 1):
            # Gemini заблокирован по региону — пропускаем
            if provider == "gemini" and self._region_unsupported:
                continue

            validation_feedback: str | None = None
            logger.info(
                "[%s] Модель %d/%d: %s (%s)",
                task_label, pos, total, model_name, provider,
            )

            for attempt in range(1, total_attempts + 1):
                prompt = prompt_fn(validation_feedback)

                # ── Запрос к провайдеру ──────────────────────
                try:
                    raw_text = await self._request_json(
                        prompt, model_name, schema, provider,
                    )
                except Exception as exc:
                    base = (
                        exc.last_attempt.exception()
                        if isinstance(exc, RetryError) and exc.last_attempt
                        else exc
                    )
                    if (
                        self._is_provider_quota_error(base, provider)
                        and pos < total
                    ):
                        logger.warning(
                            "Квота %s/%s исчерпана, переключаемся.",
                            provider, model_name,
                        )
                        break  # → следующая модель
                    raise self._build_provider_error(base, provider) from exc

                # ── Парсинг и валидация ──────────────────────
                try:
                    result = schema.model_validate_json(raw_text)
                    validate_fn(result)
                    extract_result_fn(result, attempt)
                    self.model_name = f"{provider}:{model_name}"
                    return result
                except (ValidationError, AIClientResponseError) as exc:
                    validation_feedback = self._format_reask_reason(exc)
                    logger.warning(
                        "[%s] Попытка %d/%d: %s",
                        task_label, attempt, total_attempts,
                        validation_feedback,
                    )
                    logger.debug("Сырой ответ: %s", raw_text[:500])
                    if attempt == total_attempts:
                        raise AIClientResponseError(
                            f"Не удалось получить корректный {task_label}-ответ "
                            f"после {total_attempts} попыток."
                        ) from exc

        raise AIClientResponseError(
            "Все AI-модели исчерпали квоту или недоступны."
        )

    # ════════════════════════════════════════════════════════════
    #  SOLVE — Choice
    # ════════════════════════════════════════════════════════════
    async def solve_choice_task(
        self, question: str, options: list[str]
    ) -> ChoiceResponse:
        self._validate_inputs(question, options)
        logger.info(
            "Задача 'choice': вариантов=%d, provider=%s",
            len(options), self.ai_provider,
        )

        def prompt_fn(feedback):
            return self._build_choice_prompt(
                question, options, validation_feedback=feedback,
            )

        def validate_fn(result: ChoiceResponse):
            self._validate_selected_indices(
                result.selected_indices, len(options),
            )

        def log_fn(result: ChoiceResponse, attempt: int):
            logger.info(
                "Выбраны индексы: %s (попытка %d)",
                result.selected_indices, attempt,
            )
            logger.debug("Обоснование: %s", result.reasoning[:200])

        return await self._solve_loop(
            "choice", ChoiceResponse, prompt_fn, validate_fn, log_fn,
        )

    # ════════════════════════════════════════════════════════════
    #  SOLVE — Ordering / Matching
    # ════════════════════════════════════════════════════════════
    async def solve_ordering_task(
        self,
        question: str,
        left_items: list[str],
        right_items: list[str],
    ) -> OrderingResponse:
        if not question or not question.strip():
            raise AIClientInputError("Вопрос пуст.")
        if (
            not left_items
            or not right_items
            or len(left_items) != len(right_items)
        ):
            raise AIClientInputError(
                "Списки элементов должны быть непустыми и одинаковой длины."
            )

        logger.info(
            "Задача 'ordering': left=%d, right=%d, provider=%s",
            len(left_items), len(right_items), self.ai_provider,
        )

        def prompt_fn(feedback):
            return self._build_ordering_prompt(
                question, left_items, right_items,
                validation_feedback=feedback,
            )

        def validate_fn(result: OrderingResponse):
            self._validate_ordered_indices(
                result.ordered_indices, len(right_items),
            )

        def log_fn(result: OrderingResponse, attempt: int):
            logger.info(
                "Порядок: %s (попытка %d)",
                result.ordered_indices, attempt,
            )

        return await self._solve_loop(
            "ordering", OrderingResponse, prompt_fn, validate_fn, log_fn,
        )

    # ════════════════════════════════════════════════════════════
    #  SOLVE — String
    # ════════════════════════════════════════════════════════════
    async def solve_string_task(self, question: str) -> StringResponse:
        if not question or not question.strip():
            raise AIClientInputError("Вопрос пуст.")

        logger.info("Задача 'string': provider=%s", self.ai_provider)

        def prompt_fn(feedback):
            return self._build_string_prompt(
                question, validation_feedback=feedback,
            )

        def validate_fn(result: StringResponse):
            if not result.answer or not result.answer.strip():
                raise AIClientResponseError("Модель вернула пустой answer.")

        def log_fn(result: StringResponse, attempt: int):
            logger.info("String-ответ получен (попытка %d).", attempt)

        return await self._solve_loop(
            "string", StringResponse, prompt_fn, validate_fn, log_fn,
        )
