import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.models import (
    AuthActionEnum,
    AuthAuditLog,
    EmailVerificationToken,
    OAuthAccount,
    PasswordResetToken,
    Permission,
    RoleEnum,
    RolePermission,
    Session,
    SessionStatusEnum,
    User,
    UserPermission,
    UserProfile,
)
from app.core.mongo_base import utcnow


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["users"]

    async def get_by_id(self, user_id: str) -> User | None:
        doc = await self.col.find_one({"_id": str(user_id), "is_deleted": False})
        return User.from_mongo(doc)

    async def get_by_email(self, email: str) -> User | None:
        doc = await self.col.find_one({"email": email.lower(), "is_deleted": False})
        return User.from_mongo(doc)

    async def create(self, **kwargs) -> User:
        user = User(**kwargs)
        await self.col.insert_one(user.to_mongo())
        return user

    async def _update(self, user_id: str, values: dict) -> None:
        values["updated_at"] = utcnow()
        await self.col.update_one({"_id": str(user_id)}, {"$set": values})

    async def update_last_login(self, user_id: str) -> None:
        await self._update(user_id, {"last_login": datetime.now(timezone.utc)})

    async def set_password(self, user_id: str, password_hash: str) -> None:
        await self._update(user_id, {"password_hash": password_hash})

    async def mark_verified(self, user_id: str) -> None:
        await self._update(user_id, {"is_verified": True})

    async def register_failed_login(self, user_id: str, count: int) -> None:
        await self._update(user_id, {"failed_login_count": count})

    async def lock_account(self, user_id: str, until: datetime) -> None:
        await self._update(user_id, {"is_locked": True, "locked_until": until})

    async def unlock_account(self, user_id: str) -> None:
        await self._update(
            user_id, {"is_locked": False, "locked_until": None, "failed_login_count": 0}
        )

    async def soft_delete(self, user_id: str) -> None:
        await self._update(
            user_id,
            {"is_deleted": True, "deleted_at": datetime.now(timezone.utc), "is_active": False},
        )


class SessionRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["sessions"]

    async def create(
        self,
        user_id: str,
        device_id: str,
        refresh_token_hash: str,
        refresh_token_jti: str,
        expires_at: datetime,
        device_name: str | None = None,
        os_name: str | None = None,
        browser: str | None = None,
        ip_address: str | None = None,
        location: str | None = None,
        user_agent: str | None = None,
    ) -> Session:
        record = Session(
            user_id=user_id,
            device_id=device_id,
            device_name=device_name,
            os_name=os_name,
            browser=browser,
            ip_address=ip_address,
            location=location,
            user_agent=user_agent,
            refresh_token_hash=refresh_token_hash,
            refresh_token_jti=refresh_token_jti,
            expires_at=expires_at,
        )
        await self.col.insert_one(record.to_mongo())
        return record

    async def get_by_jti(self, jti: str) -> Session | None:
        doc = await self.col.find_one({"refresh_token_jti": jti})
        return Session.from_mongo(doc)

    async def get_by_id(self, session_id: str) -> Session | None:
        doc = await self.col.find_one({"_id": str(session_id)})
        return Session.from_mongo(doc)

    async def list_active_for_user(self, user_id: str) -> list[Session]:
        cursor = self.col.find(
            {"user_id": user_id, "status": SessionStatusEnum.ACTIVE.value}
        ).sort("last_active_at", -1)
        return [Session.from_mongo(d) for d in await cursor.to_list(length=None)]

    async def touch(self, session_id: str) -> None:
        await self.col.update_one(
            {"_id": str(session_id)},
            {"$set": {"last_active_at": datetime.now(timezone.utc)}},
        )

    async def revoke(self, session_id: str) -> None:
        await self.col.update_one(
            {"_id": str(session_id)},
            {"$set": {"status": SessionStatusEnum.REVOKED.value, "revoked_at": datetime.now(timezone.utc)}},
        )

    async def revoke_by_jti(self, jti: str) -> None:
        await self.col.update_one(
            {"refresh_token_jti": jti},
            {"$set": {"status": SessionStatusEnum.REVOKED.value, "revoked_at": datetime.now(timezone.utc)}},
        )

    async def revoke_all_for_user(self, user_id: str) -> None:
        await self.col.update_many(
            {"user_id": user_id, "status": SessionStatusEnum.ACTIVE.value},
            {"$set": {"status": SessionStatusEnum.REVOKED.value, "revoked_at": datetime.now(timezone.utc)}},
        )

    async def delete_expired(self, before: datetime) -> int:
        result = await self.col.delete_many({"expires_at": {"$lt": before}})
        return result.deleted_count

    async def update_tokens(
        self, session_id: str, refresh_token_hash: str, refresh_token_jti: str, expires_at: datetime
    ) -> None:
        await self.col.update_one(
            {"_id": str(session_id)},
            {
                "$set": {
                    "refresh_token_hash": refresh_token_hash,
                    "refresh_token_jti": refresh_token_jti,
                    "last_active_at": datetime.now(timezone.utc),
                    "expires_at": expires_at,
                }
            },
        )


class EmailVerificationRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["email_verification_tokens"]

    async def create(self, user_id: str, token_hash: str, expires_at: datetime) -> EmailVerificationToken:
        record = EmailVerificationToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        await self.col.insert_one(record.to_mongo())
        return record

    async def get_by_hash(self, token_hash: str) -> EmailVerificationToken | None:
        doc = await self.col.find_one({"token_hash": token_hash})
        return EmailVerificationToken.from_mongo(doc)

    async def mark_used(self, token_id: str) -> None:
        await self.col.update_one(
            {"_id": str(token_id)}, {"$set": {"used_at": datetime.now(timezone.utc)}}
        )

    async def invalidate_all_for_user(self, user_id: str) -> None:
        await self.col.update_many(
            {"user_id": user_id, "used_at": None},
            {"$set": {"used_at": datetime.now(timezone.utc)}},
        )


class PasswordResetRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["password_reset_tokens"]

    async def create(self, user_id: str, token_hash: str, expires_at: datetime) -> PasswordResetToken:
        record = PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        await self.col.insert_one(record.to_mongo())
        return record

    async def get_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        doc = await self.col.find_one({"token_hash": token_hash})
        return PasswordResetToken.from_mongo(doc)

    async def mark_used(self, token_id: str) -> None:
        await self.col.update_one(
            {"_id": str(token_id)}, {"$set": {"used_at": datetime.now(timezone.utc)}}
        )


class PermissionRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.permissions_col = db["permissions"]
        self.role_permissions_col = db["role_permissions"]
        self.user_permissions_col = db["user_permissions"]

    async def get_by_key(self, key: str) -> Permission | None:
        doc = await self.permissions_col.find_one({"key": key})
        return Permission.from_mongo(doc)

    async def create(self, key: str, description: str | None = None, category: str | None = None) -> Permission:
        perm = Permission(key=key, description=description, category=category)
        await self.permissions_col.insert_one(perm.to_mongo())
        return perm

    async def grant_to_role(self, role: RoleEnum, permission_key: str) -> None:
        await self.role_permissions_col.update_one(
            {"role": role.value},
            {
                "$addToSet": {"permission_keys": permission_key},
                "$setOnInsert": {"_id": str(uuid.uuid4())},
                "$set": {"updated_at": utcnow()},
            },
            upsert=True,
        )

    async def grant_to_user(self, user_id: str, permission_key: str) -> None:
        await self.user_permissions_col.update_one(
            {"user_id": user_id},
            {
                "$addToSet": {"permission_keys": permission_key},
                "$setOnInsert": {"_id": str(uuid.uuid4())},
                "$set": {"updated_at": utcnow()},
            },
            upsert=True,
        )

    async def get_effective_permissions(self, user_id: str, role: RoleEnum) -> set[str]:
        role_doc = await self.role_permissions_col.find_one({"role": role.value})
        user_doc = await self.user_permissions_col.find_one({"user_id": user_id})
        role_perms = set(role_doc.get("permission_keys", [])) if role_doc else set()
        user_perms = set(user_doc.get("permission_keys", [])) if user_doc else set()
        return role_perms | user_perms


class UserProfileRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["user_profiles"]

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        doc = await self.col.find_one({"user_id": user_id})
        return UserProfile.from_mongo(doc)

    async def create_default(self, user_id: str) -> UserProfile:
        profile = UserProfile(user_id=user_id)
        await self.col.insert_one(profile.to_mongo())
        return profile

    async def update(self, user_id: str, **fields) -> UserProfile | None:
        values = {k: v for k, v in fields.items() if v is not None}
        if not values:
            return await self.get_by_user_id(user_id)
        values["updated_at"] = utcnow()
        await self.col.update_one({"user_id": user_id}, {"$set": values})
        return await self.get_by_user_id(user_id)


class OAuthAccountRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["oauth_accounts"]

    async def get_by_provider_account(self, provider: str, provider_account_id: str) -> OAuthAccount | None:
        doc = await self.col.find_one(
            {"provider": provider, "provider_account_id": provider_account_id}
        )
        return OAuthAccount.from_mongo(doc)

    async def create(self, **kwargs) -> OAuthAccount:
        account = OAuthAccount(**kwargs)
        await self.col.insert_one(account.to_mongo())
        return account


class AuditLogRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["auth_audit_logs"]

    async def log(
        self,
        action: AuthActionEnum,
        status: str,
        user_id: str | None = None,
        ip_address: str | None = None,
        device_id: str | None = None,
        request_id: str | None = None,
        metadata: dict | None = None,
    ) -> AuthAuditLog:
        entry = AuthAuditLog(
            user_id=user_id,
            action=action,
            status=status,
            ip_address=ip_address,
            device_id=device_id,
            request_id=request_id,
            metadata_json=metadata or {},
        )
        await self.col.insert_one(entry.to_mongo())
        return entry

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[AuthAuditLog]:
        cursor = self.col.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        return [AuthAuditLog.from_mongo(d) for d in await cursor.to_list(length=limit)]
