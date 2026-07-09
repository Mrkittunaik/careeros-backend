from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.models import MongoConnectionStatusEnum


class MongoConnectionCreate(BaseModel):
    mongo_uri: str = Field(..., min_length=10, description="e.g. mongodb+srv://user:pass@cluster.mongodb.net")
    database_name: str = Field(..., min_length=1, max_length=128)


class MongoConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    database_name: str
    status: MongoConnectionStatusEnum
    last_error: str | None
    last_verified_at: datetime | None
    is_enabled: bool
    # mongo_uri is intentionally never returned once saved


class QuotaUsageOut(BaseModel):
    plan: str
    unlimited: bool
    daily_used: int
    daily_limit: int | None
    monthly_used: int
    monthly_limit: int | None
    own_database_connected: bool
