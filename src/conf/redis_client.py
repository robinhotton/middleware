"""Singleton client Redis asynchrone (cache LLM + rate limiter)."""

from functools import lru_cache

import redis.asyncio as aioredis

from .settings import get_settings


@lru_cache
def get_redis_client() -> aioredis.Redis | None:
    """Retourne un client Redis partage, ou None si REDIS_URL est vide."""
    url = get_settings().REDIS_URL
    if not url:
        return None
    return aioredis.from_url(url, decode_responses=True)
