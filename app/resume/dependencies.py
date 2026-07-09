from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.integrations.dependencies import get_mongo_db_for_user
from app.resume.services import ResumeService


async def get_resume_service(db: AsyncIOMotorDatabase = Depends(get_mongo_db_for_user)) -> ResumeService:
    return ResumeService(db)
