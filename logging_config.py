import logging
import sys

from config import settings


def setup_logging() -> None:
    """Инициализирует root-логгер с единым форматом и уровнем из настроек."""
    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d — %(message)s"
    )
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # в идеале добавить logging.getLogger, чтобы уменьшить шум от сторонних библиотек
    noisy_loggers = [
        "httpx",
        "httpcore",
        "playwright",
        "asyncio",
        "google.api_core"
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)