import time

from fastapi import Depends, Request

from app.core.exceptions import RateLimitError
from app.core.redis_client import get_redis


class SlidingWindowRateLimiter:
    """Redis sorted-set sliding-window rate limiter.

    Usage as a route dependency:
        Depends(SlidingWindowRateLimiter(key_prefix="login", limit=5, window_seconds=60))

    Keys by client IP; for endpoints where a user identifier is known (e.g. by
    email during login), pass an explicit key via `key_override` on __call__.
    """

    def __init__(self, key_prefix: str, limit: int, window_seconds: int):
        self.key_prefix = key_prefix
        self.limit = limit
        self.window_seconds = window_seconds

    async def check(self, identifier: str) -> None:
        redis = get_redis()
        key = f"ratelimit:{self.key_prefix}:{identifier}"
        now = time.time()
        window_start = now - self.window_seconds

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, self.window_seconds)
        _, _, count, _ = await pipe.execute()

        if count > self.limit:
            raise RateLimitError(
                f"Too many requests. Limit is {self.limit} per {self.window_seconds}s.",
                details={"retry_after_seconds": self.window_seconds},
            )

    async def __call__(self, request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        await self.check(client_ip)


def get_client_identifier(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
