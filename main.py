import logging
import asyncio

from config import settings
from logging_config import setup_logging
from browser_manager import BrowserManager
from auth import ensure_logged_in


setup_logging()
logger = logging.getLogger(__name__)


async def main():
    logger.info("Старт программы Stepik-Solver")

    # Важно: для первого запуска HEADLESS должен быть False,
    # чтобы ты видел окно браузера и мог ввести пароль.
    if settings.headless:
        logger.warning("Внимание: HEADLESS=True. Если вы еще не авторизованы, скрипт зависнет.")

    # Используем наш менеджер контекста
    async with BrowserManager() as context:
        # При persistent context браузер часто открывает пустую вкладку по умолчанию
        # Получаем ее, чтобы не плодить окна
        page = context.pages[0] if context.pages else await context.new_page()

        # Проверяем и проходим авторизацию
        await ensure_logged_in(page)

        # Тут в будущем будет запуск основного цикла обхода курса
        logger.info("Подготовка завершена. Можно закрывать браузер.")

        # Небольшая пауза перед закрытием, чтобы полюбоваться результатом
        await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Программа остановлена пользователем (Ctrl+C).")
    except Exception as exc:
        logger.error(f"Ошибка: {exc}")
