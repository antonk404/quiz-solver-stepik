# ---------- Этап 1: сборка зависимостей ----------
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1

# Сначала зависимости (кэш Docker слоёв)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Исходный код тут не нужен, мы его заберем во втором этапе

# ---------- Этап 2: финальный образ ----------
FROM python:3.14-slim-bookworm AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Сначала копируем тяжелый .venv (он кэшируется, пока не изменятся зависимости)
COPY --from=builder /app/.venv /app/.venv

# Устанавливаем Chromium и все необходимые системные зависимости
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Только в самом конце копируем код! (Изменение кода будет пересобирать только этот легкий слой)
COPY src ./src

HEALTHCHECK --interval=2m --timeout=20s --start-period=30s --retries=3 \
    CMD python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.chromium.executable_path; p.stop()" || exit 1

CMD ["python", "-m", "src.main"]