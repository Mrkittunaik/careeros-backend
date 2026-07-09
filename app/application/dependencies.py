from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.application.service import ApplicationService
from app.integrations.dependencies import get_mongo_db_for_user


async def get_application_service(
    db: AsyncIOMotorDatabase = Depends(get_mongo_db_for_user),
) -> ApplicationService:
    return ApplicationService(db)
