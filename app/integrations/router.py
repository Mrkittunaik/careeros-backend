from fastapi import APIRouter, Depends, status

from app.auth.dependencies import get_current_active_user
from app.auth.models import RoleEnum, User
from app.core.config import settings
from app.core.quota import UNLIMITED_ROLES, get_usage
from app.integrations.dependencies import get_mongo_integration_service
from app.integrations.schemas import MongoConnectionCreate, MongoConnectionOut, QuotaUsageOut
from app.integrations.service import BYO_DATABASE_ROLES, MongoIntegrationService

router = APIRouter(prefix="/integrations/mongodb", tags=["Integrations"])


@router.get("/connection", response_model=MongoConnectionOut)
async def get_connection(
    user: User = Depends(get_current_active_user),
    service: MongoIntegrationService = Depends(get_mongo_integration_service),
) -> MongoConnectionOut:
    row = await service.get_connection(user)
    return MongoConnectionOut.model_validate(row)


@router.put("/connection", response_model=MongoConnectionOut, status_code=status.HTTP_200_OK)
async def connect_own_database(
    payload: MongoConnectionCreate,
    user: User = Depends(get_current_active_user),
    service: MongoIntegrationService = Depends(get_mongo_integration_service),
) -> MongoConnectionOut:
    """Paid-plan users only. Validates the connection string against the
    real cluster before saving; nothing is persisted if it fails.
    """
    row = await service.connect(user, payload)
    return MongoConnectionOut.model_validate(row)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_own_database(
    user: User = Depends(get_current_active_user),
    service: MongoIntegrationService = Depends(get_mongo_integration_service),
) -> None:
    """Reverts the account to the shared default MongoDB cluster."""
    await service.disconnect(user)


@router.get("/quota", response_model=QuotaUsageOut)
async def get_quota_usage(user: User = Depends(get_current_active_user)) -> QuotaUsageOut:
    daily, monthly = await get_usage(user.id)
    unlimited = user.role in UNLIMITED_ROLES
    return QuotaUsageOut(
        plan=user.role.value,
        unlimited=unlimited,
        daily_used=daily,
        daily_limit=None if unlimited else settings.QUOTA_FREE_DAILY_CALLS,
        monthly_used=monthly,
        monthly_limit=None if unlimited else settings.QUOTA_FREE_MONTHLY_CALLS,
        own_database_connected=user.role in BYO_DATABASE_ROLES,
    )
