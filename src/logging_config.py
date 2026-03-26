"""Настройка логирования проекта."""

import logging
import sys

from src.config import settings


def setup_logging() -> None:
    """Инициализирует root-логгер."""
    log_format = (
        "%(asctime)s | %(levelname)-8s | "
        "%(name)s:%(lineno)d — %(message)s"
    )
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Глушим шумные библиотеки
    noisy_loggers = (
        "aiohttp",
        "playwright",
        "asyncio",
        "google.api_core",
        "tenacity",
        "urllib3",
    )
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)