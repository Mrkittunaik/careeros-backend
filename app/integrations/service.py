from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.models import RoleEnum, User
from app.core.mongo import evict_user_mongo_client, test_mongo_uri
from app.core.mongo_base import utcnow
from app.core.security import decrypt_secret, encrypt_secret
from app.integrations.exceptions import (
    MongoConnectionNotFoundError,
    MongoConnectionValidationError,
    PlanNotEligibleError,
)
from app.integrations.models import MongoConnectionStatusEnum, UserMongoConnection
from app.integrations.schemas import MongoConnectionCreate

# Roles allowed to bring their own MongoDB. Everyone else is served from the
# shared default cluster (see app.core.mongo.get_mongo_for_user).
BYO_DATABASE_ROLES = {RoleEnum.PREMIUM_USER, RoleEnum.ENTERPRISE_USER, RoleEnum.SUPER_ADMIN}


class MongoIntegrationService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["user_mongo_connections"]

    async def _get_row(self, user_id: str) -> UserMongoConnection | None:
        doc = await self.col.find_one({"user_id": user_id})
        return UserMongoConnection.from_mongo(doc)

    async def get_connection(self, user: User) -> UserMongoConnection:
        row = await self._get_row(user.id)
        if row is None:
            raise MongoConnectionNotFoundError()
        return row

    async def connect(self, user: User, payload: MongoConnectionCreate) -> UserMongoConnection:
        if user.role not in BYO_DATABASE_ROLES:
            raise PlanNotEligibleError()

        ok, error = await test_mongo_uri(payload.mongo_uri, payload.database_name)
        if not ok:
            raise MongoConnectionValidationError(error or "unknown connection error")

        encrypted = encrypt_secret(payload.mongo_uri)
        now = datetime.now(timezone.utc)

        existing = await self.col.find_one({"user_id": user.id})
        if existing is None:
            row = UserMongoConnection(
                user_id=user.id,
                encrypted_uri=encrypted,
                database_name=payload.database_name,
                status=MongoConnectionStatusEnum.ACTIVE,
                last_verified_at=now,
                is_enabled=True,
            )
            await self.col.insert_one(row.to_mongo())
        else:
            await self.col.update_one(
                {"user_id": user.id},
                {
                    "$set": {
                        "encrypted_uri": encrypted,
                        "database_name": payload.database_name,
                        "status": MongoConnectionStatusEnum.ACTIVE.value,
                        "last_error": None,
                        "last_verified_at": now,
                        "is_enabled": True,
                        "updated_at": utcnow(),
                    }
                },
            )

        # force reconnect with the new credentials next time it's used
        evict_user_mongo_client(user.id)
        return await self._get_row(user.id)

    async def disconnect(self, user: User) -> None:
        result = await self.col.delete_one({"user_id": user.id})
        if result.deleted_count == 0:
            raise MongoConnectionNotFoundError()
        evict_user_mongo_client(user.id)

    async def resolve_own_uri(self, user: User) -> tuple[str | None, str | None]:
        """Returns (decrypted_uri, database_name) if the user has an active
        own-database connection, otherwise (None, None) so callers fall back
        to the shared default cluster.
        """
        if user.role not in BYO_DATABASE_ROLES:
            return None, None
        row = await self._get_row(user.id)
        if row is None or not row.is_enabled or row.status != MongoConnectionStatusEnum.ACTIVE:
            return None, None
        return decrypt_secret(row.encrypted_uri), row.database_name
