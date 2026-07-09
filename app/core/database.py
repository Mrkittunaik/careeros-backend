"""Primary database access for the whole app: MongoDB.

Postgres/SQLAlchemy has been removed. `get_db()` is kept as the dependency
name (so existing `Depends(get_db)` call sites don't all need renaming)
but it now yields a Motor database handle — the single default MongoDB
database that every user is on by default.

Premium/Enterprise users may additionally connect their own MongoDB
cluster (see app.integrations) for specific features that opt into
`get_mongo_db_for_user` instead of the plain default here.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.mongo import get_default_mongo_db, check_mongo_connection


async def get_db() -> AsyncIOMotorDatabase:
    """FastAPI dependency yielding the default MongoDB database."""
    return get_default_mongo_db()


# Alias with a clearer name for new code.
get_database = get_db


async def check_db_connection() -> bool:
    """Used by /health and /readiness probes."""
    return await check_mongo_connection()
