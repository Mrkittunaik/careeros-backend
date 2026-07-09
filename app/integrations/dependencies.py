from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.models import User
from app.core.database import get_db
from app.core.mongo import get_mongo_for_user
from app.core.quota import enforce_quota
from app.integrations.service import MongoIntegrationService


async def get_mongo_integration_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> MongoIntegrationService:
    return MongoIntegrationService(db)


async def get_mongo_db_for_user(
    user: User = Depends(enforce_quota),  # counts the call + enforces free-tier limits
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> AsyncIOMotorDatabase:
    """Drop-in dependency for any module: yields the shared default Mongo
    database, or the user's own connected Mongo database if they're on a
    paid plan and have one configured. Also enforces the API call quota.

    Usage: `db = Depends(get_mongo_db_for_user)` in any router.
    """
    service = MongoIntegrationService(db)
    own_uri, own_db_name = await service.resolve_own_uri(user)
    return await get_mongo_for_user(user.id, own_uri, own_db_name)
