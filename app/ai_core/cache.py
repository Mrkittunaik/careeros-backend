"""AI response cache — reduces API cost, improves speed, avoids duplicate
calls, per the master prompt's Caching System section.

Cache key: user_id + prompt_hash + model(stage) + provider
TTL: configurable per stage, 5 minutes to 24 hours.
"""

import hashlib
import json
import logging
import uuid

from app.core.redis_client import get_redis

logger = logging.getLogger("app.ai_core.cache")

_KEY_PREFIX = "ai_cache"

# Per-stage TTLs (seconds). Stages not listed use DEFAULT_TTL_SECONDS.
_STAGE_TTL_SECONDS: dict[str, int] = {
    "job_intelligence": 24 * 3600,  # job postings rarely change once fetched
    "resume_analysis": 12 * 3600,
    "ats_scoring": 6 * 3600,
    "job_matching": 6 * 3600,
    "email_analysis": 300,  # emails are one-shot; cache is only a dedupe guard
    "cover_letter": 3600,
    "cold_email": 3600,
}
DEFAULT_TTL_SECONDS = 1800


def _stable_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def build_cache_key(*, user_id: uuid.UUID | None, stage: str, provider: str | None, prompt_payload: dict) -> str:
    prompt_hash = _stable_hash(prompt_payload)
    user_part = str(user_id) if user_id else "anon"
    provider_part = provider or "any"
    return f"{_KEY_PREFIX}:{stage}:{user_part}:{provider_part}:{prompt_hash}"


class AICacheManager:
    def __init__(self):
        self.redis = get_redis()

    async def get(self, cache_key: str) -> dict | None:
        try:
            raw = await self.redis.get(cache_key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            logger.exception("ai_cache_get_failed", extra={"cache_key": cache_key})
            return None

    async def set(self, cache_key: str, value: dict, stage: str, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or _STAGE_TTL_SECONDS.get(stage, DEFAULT_TTL_SECONDS)
        try:
            await self.redis.set(cache_key, json.dumps(value, default=str), ex=ttl)
        except Exception:  # noqa: BLE001
            logger.exception("ai_cache_set_failed", extra={"cache_key": cache_key})

    async def invalidate(self, cache_key: str) -> None:
        try:
            await self.redis.delete(cache_key)
        except Exception:  # noqa: BLE001
            logger.exception("ai_cache_invalidate_failed", extra={"cache_key": cache_key})
