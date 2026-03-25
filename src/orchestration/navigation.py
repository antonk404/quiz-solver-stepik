"""Навигация в браузере Stepik."""

import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.config import settings

logger = logging.getLogger(__name__)

# CSS-классы Stepik — стабильны, не зависят от языка
_PERMANENT_NEXT_SELECTORS = (
    ".lesson__nav-button_next",
)

_PERMANENT_COOKIE_SELECTORS = (
    "[class*=cookie] button",
)


def _build_next_step_selectors() -> tuple[str, ...]:
    """Строит селекторы из конфига + постоянных CSS-классов."""
    dynamic = []
    for text in settings.next_step_text:
        dynamic.append(f"button:has-text('{text}')")
        dynamic.append(f"a:has-text('{text}')")
    return tuple(dynamic) + _PERMANENT_NEXT_SELECTORS


def _build_cookie_selectors() -> tuple[str, ...]:
    dynamic = []
    for text in settings.cookie_accept_texts:
        dynamic.append(f"button:has-text('{text}')")
    return tuple(dynamic) + _PERMANENT_COOKIE_SELECTORS


class Navigator:
    """Навигация по страницам Stepik."""

    def __init__(self, page: Page) -> None:
        self._page = page
        self._next_selectors = _build_next_step_selectors()
        self._cookie_selectors = _build_cookie_selectors()

    async def go_next_step(self) -> bool:
        """Нажимает «Следующий шаг». Возвращает True если удалось."""
        for sel in self._next_selectors:
            btn = self._page.locator(sel).first
            try:
                if await btn.is_visible():
                    await btn.click()
                    await self._page.wait_for_timeout(1500)
                    logger.debug("Переход: %s", sel)
                    return True
            except PlaywrightTimeoutError:
                continue
        return False

    async def dismiss_cookie_banner(self) -> None:
        """Закрывает баннер cookies."""
        for sel in self._cookie_selectors:
            btn = self._page.locator(sel).first
            try:
                if await btn.is_visible():
                    await btn.click()
                    logger.debug("Cookie-баннер закрыт.")
                    return
            except PlaywrightTimeoutError:
                continue

    async def reload(self) -> None:
        """Перезагружает страницу."""
        await self._page.reload(wait_until="domcontentloaded")
        await self._page.wait_for_timeout(800)

    async def goto(self, url: str) -> None:
        """Переходит по URL."""
        await self._page.goto(url, wait_until="domcontentloaded")
        await self._page.wait_for_timeout(800)
