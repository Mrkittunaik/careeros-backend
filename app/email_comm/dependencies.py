from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.integrations.dependencies import get_mongo_db_for_user
from app.email_comm.service import EmailAccountService, EmailIngestionService, EmailQueryService


async def get_email_account_service(db: AsyncIOMotorDatabase = Depends(get_mongo_db_for_user)) -> EmailAccountService:
    return EmailAccountService(db)


async def get_email_ingestion_service(db: AsyncIOMotorDatabase = Depends(get_mongo_db_for_user)) -> EmailIngestionService:
    return EmailIngestionService(db)


async def get_email_query_service(db: AsyncIOMotorDatabase = Depends(get_mongo_db_for_user)) -> EmailQueryService:
    return EmailQueryService(db)
