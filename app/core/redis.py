"""Redis connection management."""
import logging

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_redis: Redis | None = None


async def get_redis() -> Redis:
    """Get or create Redis connection."""
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
