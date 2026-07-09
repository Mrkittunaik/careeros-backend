import enum
from datetime import datetime

from app.core.mongo_base import MongoDocument


class MongoConnectionStatusEnum(str, enum.Enum):
    UNVERIFIED = "unverified"
    ACTIVE = "active"
    FAILED = "failed"


class UserMongoConnection(MongoDocument):
    """A user-supplied ('bring your own database') MongoDB connection.
    Collection: user_mongo_connections (one document per user).

    Only available to paid plans (PREMIUM_USER / ENTERPRISE_USER). Free-tier
    users are always served from the shared default MongoDB cluster. The
    connection string is stored AES-256-GCM encrypted (see
    app.core.security.encrypt_secret) — never in plaintext.
    """

    user_id: str
    encrypted_uri: str
    database_name: str

    status: MongoConnectionStatusEnum = MongoConnectionStatusEnum.UNVERIFIED
    last_error: str | None = None
    last_verified_at: datetime | None = None
    is_enabled: bool = True
