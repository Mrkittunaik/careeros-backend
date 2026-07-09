"""MongoDB access layer.

Two ways a request ends up with a Mongo database handle:

1. Default / shared cluster — used by every user on the free plan. One
   client is created at process startup and reused for the app's lifetime.
2. Bring-your-own-database — paid-plan users may connect their own Mongo
   cluster (see app.integrations). Their connection string is stored
   encrypted in Postgres and a dedicated motor client is created lazily
   and cached per user, so we don't reconnect on every request.

`get_mongo_for_user()` is the single entry point everything else should
use — it picks the right one automatically.
"""

import asyncio
from typing import Optional
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from app.core.config import settings

# --- Default / shared client (free tier + fallback) ---

_default_client: Optional[AsyncIOMotorClient] = None


def get_default_mongo_client() -> AsyncIOMotorClient:
    global _default_client
    if _default_client is None:
        _default_client = AsyncIOMotorClient(
            settings.MONGO_DEFAULT_URI,
            serverSelectionTimeoutMS=5000,
            maxPoolSize=50,
        )
    return _default_client


def get_default_mongo_db() -> AsyncIOMotorDatabase:
    return get_default_mongo_client()[settings.MONGO_DEFAULT_DB_NAME]


async def check_mongo_connection() -> bool:
    """Used by /health and /readiness probes."""
    try:
        await get_default_mongo_client().admin.command("ping")
        return True
    except Exception:
        return False


# --- Per-user (bring-your-own-database) clients ---
# Small in-process cache so we don't open a new TCP connection to the
# user's cluster on every request. Entries are evicted on disconnect or
# when the connection string changes (see integrations.service).

_user_clients: dict[str, AsyncIOMotorClient] = {}
_lock = asyncio.Lock()


async def get_user_mongo_client(user_id: UUID, mongo_uri: str) -> AsyncIOMotorClient:
    key = str(user_id)
    client = _user_clients.get(key)
    if client is not None:
        return client
    async with _lock:
        client = _user_clients.get(key)
        if client is None:
            client = AsyncIOMotorClient(
                mongo_uri,
                serverSelectionTimeoutMS=5000,
                maxPoolSize=10,
            )
            _user_clients[key] = client
        return client


def evict_user_mongo_client(user_id: UUID) -> None:
    """Call when a user disconnects or rotates their own DB connection."""
    client = _user_clients.pop(str(user_id), None)
    if client is not None:
        client.close()


async def test_mongo_uri(mongo_uri: str, db_name: str) -> tuple[bool, Optional[str]]:
    """Verify a candidate connection string actually works before we save it."""
    client: Optional[AsyncIOMotorClient] = None
    try:
        client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=4000)
        await client.admin.command("ping")
        # touch the target database so obvious auth/db-name issues surface now
        await client[db_name].list_collection_names()
        return True, None
    except PyMongoError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - surfacing to the caller as a validation error
        return False, str(exc)
    finally:
        if client is not None:
            client.close()


async def get_mongo_for_user(
    user_id: UUID,
    own_mongo_uri: Optional[str],
    own_db_name: Optional[str],
) -> AsyncIOMotorDatabase:
    """Resolve the Mongo database a given user's request should read/write.

    If the user has a verified, active own-database connection (paid plan),
    use it. Otherwise fall back to the shared default database.
    """
    if own_mongo_uri:
        client = await get_user_mongo_client(user_id, own_mongo_uri)
        return client[own_db_name or settings.MONGO_DEFAULT_DB_NAME]
    return get_default_mongo_db()
