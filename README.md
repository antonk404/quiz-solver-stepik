# Stepik Fill Bot

Bot for solving Stepik quiz steps with Gemini + Playwright.

## What It Supports

- choice quizzes (single/multi select)
- string answer quizzes
- matching/order quizzes, including drag-and-drop matching

## Quick Start (Windows `cmd.exe`)

```cmd
copy .env_example .env
```

Fill `GEMINI_API_KEY` in `.env`.

By default `AI_PROVIDER=gemini`, so only `GEMINI_API_KEY` is required.

Optional providers:

- `AI_PROVIDER=groq` requires `GROQ_API_KEY` (and optional `GROQ_MODEL`).
- `AI_PROVIDER=auto` uses Gemini first and then Groq fallback; set at least one key (`GEMINI_API_KEY` and/or `GROQ_API_KEY`).

Install dependencies (choose one option):

```cmd
pip install -e .
```

or with uv:

```cmd
uv sync
```

Run:

```cmd
python main.py
```

## Notes

- Browser profile is stored in `STEPIK_USER_DATA_DIR` (default: `./browser_session`).
- On first run, bot may wait for manual Stepik login and then reuse the session.
- Fast mode is enabled by default (`FAST_MODE=true`) to reduce retries and waits.
- If a step is marked wrong, the bot clicks `Solve again`/`Решить снова` and retries automatically (default `STEP_SOLVE_ATTEMPTS=2`).
- If Gemini returns `FAILED_PRECONDITION: User location is not supported`, auto-solving is paused and the browser stays open for manual solving.
