from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.service import AICoreService
from app.core.database import get_db


async def get_ai_core_service(session: AsyncSession = Depends(get_db)) -> AICoreService:
    return AICoreService(session)
