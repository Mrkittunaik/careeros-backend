"""Per-user API call quota tracking.

Free-tier users are capped on daily + monthly API calls (see
settings.QUOTA_FREE_DAILY_CALLS / QUOTA_FREE_MONTHLY_CALLS). Paid plans
(PREMIUM_USER, ENTERPRISE_USER, SUPER_ADMIN) are unlimited and are also the
only roles allowed to connect their own MongoDB (app.integrations).

Counters live in Redis as simple INCR keys with an expiry, so there's no
extra Postgres load and counters self-clean.
"""

from datetime import datetime, timezone

from fastapi import Depends, Request, status

from app.auth.dependencies import get_current_active_user
from app.auth.models import RoleEnum, User
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.redis_client import get_redis

UNLIMITED_ROLES = {RoleEnum.PREMIUM_USER, RoleEnum.ENTERPRISE_USER, RoleEnum.SUPER_ADMIN, RoleEnum.ADMIN}


class QuotaExceededError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "QUOTA_EXCEEDED"

    def __init__(self):
        super().__init__(
            "API call quota exceeded for your plan. Upgrade to Premium or Enterprise for unlimited usage."
        )


def _daily_key(user_id) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"quota:daily:{user_id}:{day}"


def _monthly_key(user_id) -> str:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"quota:monthly:{user_id}:{month}"


async def get_usage(user_id) -> tuple[int, int]:
    redis = get_redis()
    daily = await redis.get(_daily_key(user_id))
    monthly = await redis.get(_monthly_key(user_id))
    return int(daily or 0), int(monthly or 0)


async def increment_and_check(user: User) -> tuple[int, int]:
    """Increments both counters and raises QuotaExceededError if the free
    plan's limits are exceeded. Unlimited roles still get counted (for
    visibility/analytics) but are never blocked.
    """
    redis = get_redis()
    daily_key = _daily_key(user.id)
    monthly_key = _monthly_key(user.id)

    daily = await redis.incr(daily_key)
    if daily == 1:
        await redis.expire(daily_key, 60 * 60 * 26)  # a little over a day, tz-safe
    monthly = await redis.incr(monthly_key)
    if monthly == 1:
        await redis.expire(monthly_key, 60 * 60 * 24 * 32)

    if user.role not in UNLIMITED_ROLES:
        if daily > settings.QUOTA_FREE_DAILY_CALLS or monthly > settings.QUOTA_FREE_MONTHLY_CALLS:
            raise QuotaExceededError()

    return daily, monthly


async def enforce_quota(
    request: Request,
    user: User = Depends(get_current_active_user),
) -> User:
    """FastAPI dependency — attach to any route (or router-wide) that should
    count against the caller's plan quota.
    """
    await increment_and_check(user)
    return user
