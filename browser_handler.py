import logging
import asyncio
import random

from playwright.async_api import (
    Page, Locator,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from config import settings
from schemas import ChoiceTaskData, OrderingTaskData
from exceptions import DOMElementNotFoundError, InvalidAnswerIndicesError
from retry_utils import retry_on_dom
from validation_utils import validate_ordered_indices, validate_selected_indices

logger = logging.getLogger(__name__)


class StepikBrowserHandler:
    """Класс для взаимодействия с DOM-деревом курсов Stepik."""

    def __init__(self, page: Page):
        self.page = page

        # ── Таймеры ──────────────────────────────────────────────
        if settings.fast_mode:
            self.CLICK_DELAY_SEC = 0.0
            self.CLICK_DELAY_JITTER_SEC = 0.0
            self.SUBMIT_WAIT_TIMEOUT_MS = settings.submit_wait_timeout_ms
            self.SUBMIT_RETRY_DELAY_MS = 100
        else:
            self.CLICK_DELAY_SEC = 0.3
            self.CLICK_DELAY_JITTER_SEC = 0.15
            self.SUBMIT_WAIT_TIMEOUT_MS = 5000
            self.SUBMIT_RETRY_DELAY_MS = 300

        # ── Общие селекторы ──────────────────────────────────────
        self.FEEDBACK_SELECTOR = ".attempt-message"
        self._feedback_baseline: tuple[str, str] | None = None

        self.QUESTION_SELECTOR = ".step-text, .html-content, .step-inner"
        self.QUIZ_WRAPPER = ".attempt-wrapper"

        # ── Choice (тест) ────────────────────────────────────────
        self.OPTION_SELECTOR = (
            ".reply-label, .choice-quiz__label, "
            "label.s-checkbox, label.s-radio"
        )
        self.OPTION_INPUT_SELECTOR = "input[type='checkbox'], input[type='radio']"

        # ── Кнопка «Отправить» ───────────────────────────────────
        self.SUBMIT_BUTTON_CANDIDATES = (
            "button.submit-submission",
            "button[data-qa='submit-submission']",
            "button.s-btn[type='submit']",
            "button[type='submit']",
            "button:has-text('Отправить')",
        )

        # ══════════════════════════════════════════════════════════
        #  MATCHING — сопоставление (два столбца: термин ↔ определение)
        #
        #  Реальная структура Stepik:
        #    .matching-quiz
        #      .matching-quiz__left          ← фиксированные термины
        #        .dnd-quiz__item
        #          .dnd-quiz__item-content    ← текст термина
        #      .matching-quiz__right         ← перестраиваемые определения
        #        .dnd-quiz__item
        #          .dnd-quiz__item-handle     ← иконка «⠿» для DnD
        #          .dnd-quiz__item-content    ← текст определения
        #          .dnd-quiz__item-actions    ← кнопки ↑ ↓
        #            button (1-й = Move up)
        #            button (2-й = Move down)
        # ══════════════════════════════════════════════════════════
        self.MATCHING_QUIZ = ".matching-quiz"
        self.MATCHING_LEFT = ".matching-quiz__left"
        self.MATCHING_RIGHT = ".matching-quiz__right"
        self.MATCHING_ITEM = ".dnd-quiz__item"
        self.MATCHING_ITEM_CONTENT = ".dnd-quiz__item-content"
        self.MATCHING_ITEM_ACTIONS = ".dnd-quiz__item-actions"

        # ── Ordering (сортировка списка) ─────────────────────────
        self.ORDERING_INDICATOR = ".sortable-list, .ordering-quiz"
        self.ORDERING_ITEM = ".sortable-list__item, .ordering-quiz__item"

        # ── Кэш ─────────────────────────────────────────────────
        self._last_matching_definitions: list[str] = []
        self._last_ordering_right_items: list[str] = []

    # ================================================================
    #  УТИЛИТЫ
    # ================================================================
    def _scoped(self, sub_selector: str) -> str:
        """Безопасно скоупит КАЖДЫЙ суб-селектор
        через запятую внутрь QUIZ_WRAPPER."""
        parts = []
        for s in sub_selector.split(","):
            s = s.strip()
            if s:
                parts.append(f"{self.QUIZ_WRAPPER} {s}")
        return ", ".join(parts)

    @staticmethod
    def _normalize_choice_indices_fast(
        selected_indices: list[int], options_count: int
    ) -> list[int]:
        normalized, seen = [], set()
        for raw in selected_indices:
            if isinstance(raw, int) and 0 <= raw < options_count and raw not in seen:
                seen.add(raw)
                normalized.append(raw)
        return normalized

    @staticmethod
    def _normalize_ordered_indices_fast(
        ordered_indices: list[int], items_count: int
    ) -> list[int]:
        normalized, seen = [], set()
        for raw in ordered_indices:
            if isinstance(raw, int) and 0 <= raw < items_count and raw not in seen:
                seen.add(raw)
                normalized.append(raw)
        for idx in range(items_count):
            if idx not in seen:
                normalized.append(idx)
        return normalized

    @staticmethod
    def _clean_text(raw: str) -> str:
        """Нормализует пробелы и убирает невидимые символы."""
        import re
        return re.sub(r"\s+", " ", raw).strip()

    async def _read_feedback_signature(self) -> tuple[str, str] | None:
        loc = self.page.locator(self.FEEDBACK_SELECTOR).first
        if await loc.count() == 0:
            return None
        try:
            cls = (await loc.get_attribute("class") or "").strip()
            txt = (await loc.text_content() or "").strip()
            return cls, txt
        except PlaywrightTimeoutError:
            return None

    # ================================================================
    #  КНОПКА «ОТПРАВИТЬ»
    # ================================================================
    async def _find_visible_submit_button(self) -> Locator | None:
        for selector in self.SUBMIT_BUTTON_CANDIDATES:
            btns = self.page.locator(f"{self.QUIZ_WRAPPER} {selector}")
            try:
                for i in range(await btns.count()):
                    btn = btns.nth(i)
                    if await btn.is_visible():
                        return btn
            except PlaywrightTimeoutError:
                continue
        return None

    async def _is_submit_button_clickable(self, btn: Locator) -> bool:
        try:
            await btn.scroll_into_view_if_needed(timeout=1500)
            if not await btn.is_enabled():
                return False
            blocked = await btn.evaluate(
                "(n) => n.hasAttribute('disabled') || n.disabled "
                "|| n.getAttribute('aria-disabled') === 'true'"
            )
            if blocked:
                return False
            await btn.click(trial=True, timeout=1500)
            return True
        except (PlaywrightTimeoutError, PlaywrightError):
            return False

    async def _wait_for_clickable_submit_button(self) -> Locator:
        try:
            await self.page.wait_for_selector(
                self.QUIZ_WRAPPER, state="attached",
                timeout=self.SUBMIT_WAIT_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            raise DOMElementNotFoundError("Обёртка задания не найдена.")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.SUBMIT_WAIT_TIMEOUT_MS / 1000

        while loop.time() < deadline:
            btn = await self._find_visible_submit_button()
            if btn is not None and await self._is_submit_button_clickable(btn):
                return btn
            await self.page.wait_for_timeout(self.SUBMIT_RETRY_DELAY_MS)

        raise DOMElementNotFoundError(
            "Кнопка отправки не найдена или не кликабельна."
        )

    async def click_submit_button(self) -> None:
        btn = await self._wait_for_clickable_submit_button()
        self._feedback_baseline = await self._read_feedback_signature()
        await btn.click()
        logger.info("Кнопка «Отправить» нажата.")

    # ================================================================
    #  CHOICE — тест с вариантами
    # ================================================================
    @retry_on_dom
    async def extract_choice_task(self) -> ChoiceTaskData:
        await self.page.wait_for_selector(
            self.QUIZ_WRAPPER, state="visible", timeout=10_000,
        )
        await self.page.wait_for_selector(
            self.QUESTION_SELECTOR, state="attached", timeout=10_000,
        )
        await self.page.wait_for_selector(
            self.OPTION_SELECTOR, state="attached", timeout=10_000,
        )

        q = await (
            self.page.locator(self.QUESTION_SELECTOR)
            .first.inner_text(timeout=5000)
        )
        opts_loc = self.page.locator(self.OPTION_SELECTOR)
        cnt = await opts_loc.count()
        if cnt == 0:
            raise DOMElementNotFoundError("Блок вариантов ответов пуст.")

        opts = [
            await opts_loc.nth(i).inner_text(timeout=5000)
            for i in range(cnt)
        ]
        return ChoiceTaskData(
            question=q.strip(),
            options=[o.strip() for o in opts],
        )

    @retry_on_dom
    async def submit_choice_answer(self, selected_indices: list[int]) -> None:
        opts_loc = self.page.locator(self.OPTION_SELECTOR)
        cnt = await opts_loc.count()

        if not settings.fast_mode:
            validate_selected_indices(
                selected_indices, cnt, exc_type=InvalidAnswerIndicesError,
            )
        else:
            selected_indices = self._normalize_choice_indices_fast(
                selected_indices, cnt,
            )

        selected_set = set(selected_indices)

        for idx in range(cnt):
            el = opts_loc.nth(idx)
            is_on = await el.evaluate(
                """(node, sel) => {
                    const inp = node.tagName === 'INPUT'
                        ? node : node.querySelector(sel);
                    return inp ? inp.checked
                               : node.classList.contains('checked');
                }""",
                self.OPTION_INPUT_SELECTOR,
            )
            want = idx in selected_set

            if is_on != want:
                await el.scroll_into_view_if_needed()
                await el.click()
                await asyncio.sleep(
                    max(0.0, self.CLICK_DELAY_SEC
                        + random.uniform(-self.CLICK_DELAY_JITTER_SEC,
                                          self.CLICK_DELAY_JITTER_SEC))
                )

        await self.click_submit_button()

    # ================================================================
    #  STRING — ввод текста
    # ================================================================
    @retry_on_dom
    async def extract_string_task(self) -> str:
        await self.page.wait_for_selector(
            self.QUIZ_WRAPPER, state="visible", timeout=10_000,
        )
        return await (
            self.page.locator(self.QUESTION_SELECTOR)
            .first.inner_text(timeout=5000)
        )

    @retry_on_dom
    async def submit_string_answer(self, answer: str) -> None:
        field = self.page.locator("textarea, input[type='text']").first
        await field.wait_for(state="visible", timeout=5000)
        await field.fill(answer)
        await self.click_submit_button()

    # ================================================================
    #  MATCHING — сопоставление (перестановка правого столбца)
    #
    #  Механика Stepik: оба столбца содержат .dnd-quiz__item.
    #  Левый зафиксирован, правый — перестраиваемый.
    #  У каждого элемента справа есть кнопки ↑ ↓.
    #  Нужно переупорядочить правый столбец так, чтобы
    #  определение[i] соответствовало термину[i].
    #
    #  Стратегия: Selection Sort через кнопку «Move up».
    # ================================================================
    @retry_on_dom
    async def extract_matching_task(self) -> OrderingTaskData:
        """
        Извлекает термины (левый столбец) и определения (правый столбец).

        Возвращает ``OrderingTaskData``:
        * ``left_items``  — термины (фиксированные)
        * ``right_items`` — определения (текущий порядок, будет изменён)
        """
        await self.page.wait_for_selector(
            self.QUIZ_WRAPPER, state="visible", timeout=10_000,
        )

        # Ждём появления виджета сопоставления
        matching_sel = f"{self.QUIZ_WRAPPER} {self.MATCHING_QUIZ}"
        try:
            await self.page.wait_for_selector(
                matching_sel, state="visible", timeout=10_000,
            )
        except PlaywrightTimeoutError:
            raise DOMElementNotFoundError(
                f"Виджет сопоставления ({self.MATCHING_QUIZ}) не найден."
            )

        question = await (
            self.page.locator(self.QUESTION_SELECTOR)
            .first.inner_text(timeout=5000)
        )

        # ── Левый столбец: термины ──────────────────────────────
        left_content_sel = (
            f"{self.QUIZ_WRAPPER} {self.MATCHING_LEFT} "
            f"{self.MATCHING_ITEM} {self.MATCHING_ITEM_CONTENT}"
        )
        left_loc = self.page.locator(left_content_sel)
        left_count = await left_loc.count()

        if left_count == 0:
            raise DOMElementNotFoundError(
                "Не найдены термины в левом столбце "
                f"(селектор: {left_content_sel})."
            )

        left_items = []
        for i in range(left_count):
            raw = await left_loc.nth(i).inner_text(timeout=5000)
            left_items.append(self._clean_text(raw))

        # ── Правый столбец: определения ─────────────────────────
        right_content_sel = (
            f"{self.QUIZ_WRAPPER} {self.MATCHING_RIGHT} "
            f"{self.MATCHING_ITEM} {self.MATCHING_ITEM_CONTENT}"
        )
        right_loc = self.page.locator(right_content_sel)
        right_count = await right_loc.count()

        if right_count == 0:
            raise DOMElementNotFoundError(
                "Не найдены определения в правом столбце "
                f"(селектор: {right_content_sel})."
            )

        right_items = []
        for i in range(right_count):
            raw = await right_loc.nth(i).inner_text(timeout=5000)
            right_items.append(self._clean_text(raw))

        if left_count != right_count:
            raise DOMElementNotFoundError(
                f"Количество терминов ({left_count}) ≠ "
                f"количество определений ({right_count})."
            )

        # Кэшируем для submit
        self._last_matching_definitions = right_items.copy()

        logger.info(
            "Matching: terms=%s, definitions=%s",
            left_items, right_items,
        )

        return OrderingTaskData(
            question=self._clean_text(question),
            left_items=left_items,
            right_items=right_items,
        )

    @retry_on_dom
    async def submit_matching_answer(self, ordered_indices: list[int]) -> None:
        """
        Переупорядочивает правый столбец кнопками ↑.

        ``ordered_indices[i] = j`` означает:
        определение ``right_items[j]`` должно встать на позицию ``i``
        (напротив ``left_items[i]``).

        Алгоритм: Selection Sort —
        для каждой позиции сверху вниз находим нужный элемент
        и «всплываем» его наверх кнопкой «Move up».
        """
        if not self._last_matching_definitions:
            raise DOMElementNotFoundError(
                "Сначала вызовите extract_matching_task()."
            )

        n = len(self._last_matching_definitions)

        if not settings.fast_mode:
            validate_ordered_indices(
                ordered_indices, n, exc_type=InvalidAnswerIndicesError,
            )
        else:
            ordered_indices = self._normalize_ordered_indices_fast(
                ordered_indices, n,
            )

        # desired_texts[i] — текст, который должен оказаться на позиции i
        desired_texts = [
            self._last_matching_definitions[idx]
            for idx in ordered_indices
        ]

        # Селектор всех элементов правого столбца
        right_item_sel = (
            f"{self.QUIZ_WRAPPER} {self.MATCHING_RIGHT} "
            f"{self.MATCHING_ITEM}"
        )

        for target_pos in range(n):
            desired = desired_texts[target_pos]

            # ── Найти текущую позицию нужного элемента ───────────
            items = self.page.locator(right_item_sel)
            items_count = await items.count()
            current_pos: int | None = None

            for i in range(target_pos, items_count):
                content = items.nth(i).locator(self.MATCHING_ITEM_CONTENT)
                raw = await content.inner_text(timeout=3000)
                if self._clean_text(raw) == desired:
                    current_pos = i
                    break

            if current_pos is None:
                raise DOMElementNotFoundError(
                    f"Определение «{desired}» не найдено в правом столбце "
                    f"(позиции {target_pos}–{items_count - 1})."
                )

            if current_pos == target_pos:
                logger.debug(
                    "Позиция %d: «%s» уже на месте.", target_pos, desired,
                )
                continue

            # ── Двигаем элемент вверх кнопкой ↑ ──────────────────
            moves = current_pos - target_pos
            logger.debug(
                "Позиция %d: «%s» сейчас на %d, нужно %d нажатий ↑.",
                target_pos, desired, current_pos, moves,
            )

            for step in range(moves):
                # После каждого клика DOM обновляется (Ember re-render)
                # → переопрашиваем элементы
                items = self.page.locator(right_item_sel)
                pos_now = current_pos - step
                item = items.nth(pos_now)

                # Кнопка ↑ — первая кнопка в блоке .dnd-quiz__item-actions
                up_btn = item.locator(
                    f"{self.MATCHING_ITEM_ACTIONS} button"
                ).first

                # Проверяем, не disabled ли
                is_disabled = await up_btn.evaluate(
                    "(b) => b.disabled || b.hasAttribute('disabled')"
                )
                if is_disabled:
                    logger.warning(
                        "Кнопка ↑ disabled на позиции %d — пропускаем.",
                        pos_now,
                    )
                    break

                await up_btn.scroll_into_view_if_needed()
                await up_btn.click()

                # Ждём Ember re-render
                await self.page.wait_for_timeout(
                    150 if settings.fast_mode else 300
                )

        logger.info("Matching: все определения расставлены.")
        await self.click_submit_button()

    # ================================================================
    #  ORDERING — сортировка списка (generic DnD)
    # ================================================================
    async def _extract_ordering_lists(
        self,
    ) -> tuple[list[str], list[str]]:
        """Извлекает left/right списки для generic ordering задачи."""
        payload = await self.page.evaluate(
            """(cfg) => {
                const wrapper = document.querySelector(cfg.wrapper);
                if (!wrapper) return {left: [], right: []};

                const right = [];
                const draggables = Array.from(
                    wrapper.querySelectorAll(cfg.draggables)
                );
                for (const drag of draggables) {
                    const t = drag.innerText.trim();
                    if (t) right.push(t);
                }

                return {left: [], right};
            }""",
            {
                "wrapper": self.QUIZ_WRAPPER,
                "draggables": self.ORDERING_ITEM,
            },
        )
        return payload.get("left", []), payload.get("right", [])

    @retry_on_dom
    async def extract_ordering_task(self) -> OrderingTaskData:
        await self.page.wait_for_selector(
            self.QUIZ_WRAPPER, state="visible", timeout=10_000,
        )
        question = await (
            self.page.locator(self.QUESTION_SELECTOR)
            .first.inner_text(timeout=5000)
        )

        left, right = await self._extract_ordering_lists()

        if not right:
            raise DOMElementNotFoundError(
                "Не удалось извлечь элементы ordering-задачи."
            )

        self._last_ordering_right_items = right.copy()
        logger.info("Ordering задача: items=%d", len(right))

        return OrderingTaskData(
            question=question.strip(),
            left_items=left if left else right,
            right_items=right,
        )

    @retry_on_dom
    async def submit_ordering_answer(
        self, ordered_indices: list[int]
    ) -> None:
        if not self._last_ordering_right_items:
            raise DOMElementNotFoundError(
                "Сначала вызовите extract_ordering_task()."
            )

        n = len(self._last_ordering_right_items)

        if not settings.fast_mode:
            validate_ordered_indices(
                ordered_indices, n, exc_type=InvalidAnswerIndicesError,
            )
        else:
            ordered_indices = self._normalize_ordered_indices_fast(
                ordered_indices, n,
            )

        # Для ordering используем тот же алгоритм с кнопками ↑
        desired_texts = [
            self._last_ordering_right_items[idx]
            for idx in ordered_indices
        ]

        item_sel = self._scoped(self.ORDERING_ITEM)

        for target_pos in range(n):
            desired = desired_texts[target_pos]

            items = self.page.locator(item_sel)
            current_pos: int | None = None

            for i in range(target_pos, await items.count()):
                raw = await items.nth(i).inner_text(timeout=3000)
                if self._clean_text(raw) == self._clean_text(desired):
                    current_pos = i
                    break

            if current_pos is None:
                raise DOMElementNotFoundError(
                    f"Элемент «{desired}» не найден."
                )

            for step in range(current_pos - target_pos):
                items = self.page.locator(item_sel)
                pos_now = current_pos - step
                item = items.nth(pos_now)
                up_btn = item.locator(
                    f"{self.MATCHING_ITEM_ACTIONS} button"
                ).first

                is_disabled = await up_btn.evaluate(
                    "(b) => b.disabled || b.hasAttribute('disabled')"
                )
                if is_disabled:
                    break

                await up_btn.scroll_into_view_if_needed()
                await up_btn.click()
                await self.page.wait_for_timeout(
                    150 if settings.fast_mode else 300
                )

        await self.click_submit_button()

    # ================================================================
    #  СТАТУСЫ И ТИП ЗАДАНИЯ
    # ================================================================
    async def get_feedback_status(self) -> bool | None:
        loc = self.page.locator(self.FEEDBACK_SELECTOR).first
        try:
            await loc.wait_for(
                state="visible",
                timeout=settings.feedback_wait_timeout_ms,
            )
        except PlaywrightTimeoutError:
            return None

        if self._feedback_baseline is not None:
            bl_cls, bl_txt = self._feedback_baseline
            try:
                await self.page.wait_for_function(
                    """([sel, pc, pt]) => {
                        const n = document.querySelector(sel);
                        if (!n) return false;
                        return (n.getAttribute('class')||'').trim() !== pc
                            || (n.textContent||'').trim() !== pt;
                    }""",
                    arg=[self.FEEDBACK_SELECTOR, bl_cls, bl_txt],
                    timeout=settings.feedback_wait_timeout_ms,
                )
            except PlaywrightTimeoutError:
                pass

        classes = await loc.get_attribute("class") or ""
        self._feedback_baseline = await self._read_feedback_signature()

        if "correct" in classes:
            logger.info("Ответ принят: ВЕРНО!")
            return True
        if "wrong" in classes:
            logger.warning("Ответ отклонён: НЕВЕРНО!")
            return False
        return None

    async def get_current_feedback_status(self) -> bool | None:
        loc = self.page.locator(self.FEEDBACK_SELECTOR).first
        if await loc.count() == 0:
            return None
        classes = (await loc.get_attribute("class") or "").lower()
        if "correct" in classes:
            return True
        if "wrong" in classes:
            return False
        return None

    async def get_task_type(self) -> str:
        """
        Определяет тип задания по DOM-маркерам.

        Порядок: matching → ordering → choice → string → unknown
        """
        try:
            await self.page.wait_for_selector(
                self.QUIZ_WRAPPER, state="attached", timeout=2000,
            )
        except PlaywrightTimeoutError:
            pass

        # 1. Matching — .matching-quiz внутри обёртки
        if await self.page.locator(
            f"{self.QUIZ_WRAPPER} {self.MATCHING_QUIZ}"
        ).count() > 0:
            return "matching"

        # 2. Ordering — .sortable-list или .ordering-quiz
        if await self.page.locator(
            self._scoped(self.ORDERING_INDICATOR)
        ).count() > 0:
            return "ordering"

        # 3. Choice — чекбоксы / радио-кнопки
        if await self.page.locator(
            self._scoped(self.OPTION_SELECTOR)
        ).count() > 0:
            return "choice"

        # 4. String — текстовое поле
        if await self.page.locator(
            self._scoped("textarea, input[type='text']")
        ).count() > 0:
            return "string"

        return "unknown"
