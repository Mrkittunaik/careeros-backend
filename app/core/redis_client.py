from redis.asyncio import Redis, ConnectionPool

from app.core.config import settings

_pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True, max_connections=50)


def get_redis() -> Redis:
    return Redis(connection_pool=_pool)


async def check_redis_connection() -> bool:
    try:
        redis = get_redis()
        return bool(await redis.ping())
    except Exception:
        return False
