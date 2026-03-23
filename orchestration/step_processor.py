import logging
from dataclasses import dataclass

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from tenacity import RetryError

from ai_client import AIClient
from browser_handler import StepikBrowserHandler
from src.config import settings
from exceptions import (
    AIClientRegionUnsupportedError,
    AIClientResponseError,
    DOMElementNotFoundError,
    InvalidAnswerIndicesError,
)
from .navigation import dismiss_cookie_banner

logger = logging.getLogger(__name__)
# Для неверного ответа всегда нужна минимум одна повторная попытка.
MAX_STEP_SOLVE_ATTEMPTS = max(2, settings.step_solve_attempts)


def _unwrap_retry_error(exc: Exception) -> Exception:
    if isinstance(exc, RetryError) and exc.last_attempt:
        inner = exc.last_attempt.exception()
        if isinstance(inner, Exception):
            return inner
    return exc


@dataclass(frozen=True)
class ProcessStepResult:
    success: bool
    advanced_to_next: bool = False
    ai_unavailable: bool = False


async def _click_next_step_if_available(page: Page) -> bool:
    """Пробует нажать кнопку 'Следующий шаг' внутри блока задания (уже решенного)."""
    next_button_selectors = (
        ".attempt-wrapper button:has-text('Следующий шаг')",
        ".attempt-wrapper a:has-text('Следующий шаг')",
        ".attempt-wrapper button:has-text('Далее')",
    )
    for selector in next_button_selectors:
        next_btn = page.locator(selector).first
        try:
            await next_btn.wait_for(state="visible", timeout=2000)
            await next_btn.scroll_into_view_if_needed(timeout=1500)
            await next_btn.click()
            return True
        except PlaywrightTimeoutError:
            continue
    return False


async def process_step(page: Page, ai_client: AIClient) -> ProcessStepResult:
    await dismiss_cookie_banner(page)
    handler = StepikBrowserHandler(page)

    if await _click_next_step_if_available(page):
        return ProcessStepResult(success=True, advanced_to_next=True)

    current_feedback_status = await handler.get_current_feedback_status()
    if current_feedback_status is True:
        advanced_to_next = await _click_next_step_if_available(page)
        return ProcessStepResult(success=True, advanced_to_next=advanced_to_next)

    if current_feedback_status is False:
        retried = await handler.click_retry_button_if_available()
        if retried:
            logger.info("Шаг помечен как wrong: нажали 'Решить снова' перед новой попыткой.")
        else:
            logger.warning("Шаг помечен как wrong, но кнопка 'Решить снова' не найдена. Пробуем решать напрямую.")

    task_type = await handler.get_task_type()

    if task_type == "unknown":
        return ProcessStepResult(success=True)

    for attempt in range(1, MAX_STEP_SOLVE_ATTEMPTS + 1):
        try:
            if task_type == "choice":
                task_data = await handler.extract_choice_task()
                ai_response = await ai_client.solve_choice_task(task_data.question, task_data.options)
                await handler.submit_choice_answer(ai_response.selected_indices)

            elif task_type == "matching":
                # Обработка сопоставления терминов и определений (скриншот пользователя)
                task_data = await handler.extract_matching_task()
                ai_response = await ai_client.solve_ordering_task(
                    task_data.question,
                    task_data.left_items,
                    task_data.right_items,
                )
                await handler.submit_matching_answer(ai_response.ordered_indices)

            elif task_type == "ordering":
                # Обработка сортировки списка
                task_data = await handler.extract_ordering_task()
                ai_response = await ai_client.solve_ordering_task(
                    task_data.question,
                    task_data.left_items,
                    task_data.right_items,
                )
                await handler.submit_ordering_answer(ai_response.ordered_indices)

            elif task_type == "string":
                question_text = await handler.extract_string_task()
                ai_response = await ai_client.solve_string_task(question_text)
                await handler.submit_string_answer(ai_response.answer)
            else:
                break
        except AIClientRegionUnsupportedError as exc:
            logger.warning("Gemini недоступен в текущем регионе: %s", exc)
            return ProcessStepResult(success=True, ai_unavailable=True)
        except (AIClientResponseError, DOMElementNotFoundError, InvalidAnswerIndicesError, PlaywrightTimeoutError, RetryError) as exc:
            root_exc = _unwrap_retry_error(exc)

            if isinstance(root_exc, DOMElementNotFoundError) and "кнопка отправки" in str(root_exc).lower():
                logger.warning(
                    "Кнопка отправки недоступна, пропускаем текущий шаг: %s",
                    root_exc,
                )
                advanced_to_next = await _click_next_step_if_available(page)
                return ProcessStepResult(success=True, advanced_to_next=advanced_to_next)

            logger.error("Ожидаемая ошибка при выполнении попытки %d: %s", attempt, root_exc)
            if attempt < MAX_STEP_SOLVE_ATTEMPTS:
                continue
            return ProcessStepResult(success=False)
        except Exception:
            logger.exception("Неожиданная ошибка при обработке шага (attempt=%d).", attempt)
            raise

        feedback_status = await handler.get_feedback_status()

        if feedback_status is True:
            return ProcessStepResult(success=True)

        if feedback_status is False:
            if attempt < MAX_STEP_SOLVE_ATTEMPTS:
                await handler.click_retry_button_if_available()
                logger.warning("Ответ отклонен, повторная попытка %s/%s.", attempt + 1, MAX_STEP_SOLVE_ATTEMPTS)
                continue
            logger.error("Ответ отклонен после %s попыток.", MAX_STEP_SOLVE_ATTEMPTS)
            return ProcessStepResult(success=False)

        if feedback_status is None:
            current_feedback_status = await handler.get_current_feedback_status()
            if current_feedback_status is True:
                advanced_to_next = await _click_next_step_if_available(page)
                return ProcessStepResult(success=True, advanced_to_next=advanced_to_next)

            if current_feedback_status is False:
                if attempt < MAX_STEP_SOLVE_ATTEMPTS:
                    await handler.click_retry_button_if_available()
                    logger.warning(
                        "Текущий статус ответа = wrong, повторная попытка %s/%s.",
                        attempt + 1,
                        MAX_STEP_SOLVE_ATTEMPTS,
                    )
                    continue
                logger.error("Ответ отклонен после %s попыток.", MAX_STEP_SOLVE_ATTEMPTS)
                return ProcessStepResult(success=False)

            if attempt < MAX_STEP_SOLVE_ATTEMPTS:
                logger.warning(
                    "Не удалось получить статус ответа (таймаут). Повторяем попытку %s/%s.",
                    attempt + 1,
                    MAX_STEP_SOLVE_ATTEMPTS,
                )
                continue
            logger.warning(
                "Не удалось получить статус ответа после %s попыток. Продолжаем без явного статуса.",
                MAX_STEP_SOLVE_ATTEMPTS,
            )
            return ProcessStepResult(success=True)

    return ProcessStepResult(success=True)
