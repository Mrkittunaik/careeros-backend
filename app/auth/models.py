import enum
from datetime import datetime

from pydantic import Field

from app.core.mongo_base import MongoDocument, utcnow


class RoleEnum(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    USER = "user"
    PREMIUM_USER = "premium_user"
    ENTERPRISE_USER = "enterprise_user"
    SYSTEM_SERVICE = "system_service"


class OAuthProviderEnum(str, enum.Enum):
    GOOGLE = "google"
    GITHUB = "github"
    LINKEDIN = "linkedin"


class SessionStatusEnum(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AuthActionEnum(str, enum.Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    TOKEN_REFRESH = "token_refresh"
    REGISTER = "register"
    EMAIL_VERIFIED = "email_verified"
    EMAIL_VERIFICATION_SENT = "email_verification_sent"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    PASSWORD_CHANGED = "password_changed"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    SESSION_REVOKED = "session_revoked"


# --- Permission catalog (collection-driven, dynamically assignable) ---

class Permission(MongoDocument):
    """Canonical catalog of granular permission strings, e.g. 'resume.read',
    'job.apply', 'automation.run'. Collection: permissions.
    """

    key: str
    description: str | None = None
    category: str | None = None


class RolePermission(MongoDocument):
    """Maps a role to permission keys. Collection: role_permissions.
    One document per role; `permission_keys` denormalizes the join so
    resolving a role's permissions is a single lookup.
    """

    role: RoleEnum
    permission_keys: list[str] = Field(default_factory=list)


class UserPermission(MongoDocument):
    """Per-user permission overrides, additive on top of role-derived
    grants. Collection: user_permissions (one document per user).
    """

    user_id: str
    permission_keys: list[str] = Field(default_factory=list)


class User(MongoDocument):
    """Collection: users."""

    full_name: str
    email: str
    password_hash: str | None = None
    phone: str | None = None

    is_verified: bool = False
    is_active: bool = True
    is_locked: bool = False
    locked_until: datetime | None = None
    failed_login_count: int = 0

    role: RoleEnum = RoleEnum.USER
    profile_completed: bool = False
    last_login: datetime | None = None


class Session(MongoDocument):
    """A logical login session — tracks device/IP/browser context and can
    be individually listed/revoked. Collection: sessions.
    """

    user_id: str
    device_id: str
    device_name: str | None = None
    os_name: str | None = None
    browser: str | None = None
    ip_address: str | None = None
    location: str | None = None
    user_agent: str | None = None

    refresh_token_hash: str
    refresh_token_jti: str

    status: SessionStatusEnum = SessionStatusEnum.ACTIVE
    last_active_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    revoked_at: datetime | None = None


class OAuthAccount(MongoDocument):
    """Collection: oauth_accounts."""

    user_id: str
    provider: OAuthProviderEnum
    provider_account_id: str
    encrypted_access_token: str | None = None
    encrypted_refresh_token: str | None = None
    token_expires_at: datetime | None = None


class EmailVerificationToken(MongoDocument):
    """Collection: email_verification_tokens."""

    user_id: str
    token_hash: str
    expires_at: datetime
    used_at: datetime | None = None


class PasswordResetToken(MongoDocument):
    """Collection: password_reset_tokens."""

    user_id: str
    token_hash: str
    expires_at: datetime
    used_at: datetime | None = None


class AuthAuditLog(MongoDocument):
    """Immutable audit trail for every auth-sensitive action.
    Collection: auth_audit_logs.
    """

    user_id: str | None = None
    action: AuthActionEnum
    status: str  # "success" | "failure"
    ip_address: str | None = None
    device_id: str | None = None
    request_id: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class UserProfile(MongoDocument):
    """One-to-one profile linked to a user; owned by the auth/user module
    but referenced by resume/job modules downstream. Collection: user_profiles.
    """

    user_id: str
    current_title: str | None = None
    experience_years: int | None = None
    skills: list = Field(default_factory=list)
    education: list = Field(default_factory=list)
    resume_preferences: dict = Field(default_factory=dict)
    preferred_roles: list = Field(default_factory=list)
    preferred_locations: list = Field(default_factory=list)
    salary_expectation: str | None = None
    work_mode: str | None = None  # remote/hybrid/onsite
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
