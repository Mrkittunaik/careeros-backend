import time

from fastapi import APIRouter

from app.core.database import check_db_connection
from app.core.mongo import check_mongo_connection
from app.core.redis_client import check_redis_connection

router = APIRouter(tags=["System Health"])

_START_TIME = time.time()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "uptime_seconds": round(time.time() - _START_TIME, 2)}


@router.get("/liveness")
async def liveness() -> dict:
    return {"status": "alive"}


@router.get("/readiness")
async def readiness() -> dict:
    db_ok = await check_db_connection()
    redis_ok = await check_redis_connection()
    mongo_ok = await check_mongo_connection()
    checks = {"database": db_ok, "redis": redis_ok, "mongodb": mongo_ok}
    overall_ok = all(checks.values())
    return {
        "status": "ready" if overall_ok else "not_ready",
        "checks": checks,
    }
