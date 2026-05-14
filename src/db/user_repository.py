import logging
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    ai_provider TEXT NOT NULL DEFAULT 'gemini',
    ai_api_key  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
)
"""


class UserRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str) -> "UserRepository":
        pool = await asyncpg.create_pool(dsn)
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE)
        logger.info("UserRepository initialized")
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def upsert(self, user_id: str, ai_provider: str, ai_api_key: str) -> None:
        now = datetime.now(timezone.utc)
        await self._pool.execute(
            """
            INSERT INTO users (user_id, ai_provider, ai_api_key, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $4)
            ON CONFLICT (user_id) DO UPDATE SET
                ai_provider = EXCLUDED.ai_provider,
                ai_api_key  = EXCLUDED.ai_api_key,
                updated_at  = EXCLUDED.updated_at
            """,
            user_id, ai_provider, ai_api_key, now,
        )
        logger.info("UserRepository upsert user_id=%s provider=%s", user_id, ai_provider)

    async def get(self, user_id: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT user_id, ai_provider, ai_api_key FROM users WHERE user_id = $1",
            user_id,
        )
        return dict(row) if row else None
