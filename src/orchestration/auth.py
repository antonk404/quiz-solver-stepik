"""Программная авторизация на Stepik."""

import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

LOGIN_URL = "https://stepik.org/login"

# Селекторы формы логина
_EMAIL_SELECTOR = "input[name='login'], input[type='email'], #id_login_email"
_PASSWORD_SELECTOR = "input[name='password'], input[type='password'], #id_login_password"
_SUBMIT_SELECTOR = "button[type='submit'], button:has-text('Войти'), button:has-text('Log in')"

# Признаки успешного входа
_LOGGED_IN_SELECTORS = (
    ".navbar__profile-img",
    "[class*=profile-img]",
    "[class*=avatar]",
    "a[href*='/users/']",
)


async def is_logged_in(page: Page) -> bool:
    """Проверяет, залогинен ли пользователь."""
    for sel in _LOGGED_IN_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible():
                logger.debug("Авторизован (найден %s).", sel)
                return True
        except PlaywrightTimeoutError:
            continue
    return False


async def login(page: Page, email: str, password: str) -> bool:
    """Программный логин на Stepik.

    Returns:
        True если авторизация успешна.
    """
    if not email or not password:
        logger.error(
            "STEPIK_EMAIL и STEPIK_PASSWORD не заданы в .env"
        )
        return False

    logger.info("Авторизация на Stepik (email=%s)…", email)

    # 1. Открываем страницу логина
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)

    # 2. Ищем поле email
    email_field = page.locator(_EMAIL_SELECTOR).first
    try:
        await email_field.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError:
        logger.error(
            "Поле email не найдено. "
            "Возможно, Stepik изменил форму логина."
        )
        return False

    # 3. Заполняем email
    await email_field.click()
    await email_field.fill(email)
    logger.debug("Email введён.")

    # 4. Заполняем пароль
    password_field = page.locator(_PASSWORD_SELECTOR).first
    try:
        await password_field.wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError:
        logger.error("Поле пароля не найдено.")
        return False

    await password_field.click()
    await password_field.fill(password)
    logger.debug("Пароль введён.")

    # 5. Нажимаем «Войти»
    submit_btn = page.locator(_SUBMIT_SELECTOR).first
    try:
        await submit_btn.wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError:
        logger.error("Кнопка 'Войти' не найдена.")
        return False

    await submit_btn.click()
    logger.debug("Кнопка 'Войти' нажата.")

    # 6. Ждём результат
    try:
        await page.wait_for_url(
            lambda url: "/login" not in url,
            timeout=15_000,
        )
    except PlaywrightTimeoutError:
        # Проверяем ошибку авторизации
        error_msg = page.locator(
            ".sign-form__error, .notification--error, "
            "[class*=error], [class*=alert]"
        ).first
        try:
            if await error_msg.is_visible():
                text = await error_msg.text_content()
                logger.error("Ошибка входа: %s", text)
                return False
        except PlaywrightTimeoutError:
            pass

        logger.error("Таймаут авторизации — страница не перенаправилась.")
        return False

    # 7. Проверяем что залогинились
    await page.wait_for_timeout(2000)
    if await is_logged_in(page):
        logger.info("✅ Авторизация успешна!")
        return True

    logger.error("Авторизация не удалась (профиль не найден).")
    return False
