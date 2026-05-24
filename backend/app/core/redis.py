from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True, max_connections=20)
    return _pool
