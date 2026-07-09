from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.exceptions import InsufficientPermissionsError
from app.auth.models import RoleEnum, User
from app.auth.services import AuthService
from app.core.database import get_db
from app.core.rate_limiter import SlidingWindowRateLimiter
from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=True)


async def get_auth_service(db: AsyncIOMotorDatabase = Depends(get_db)) -> AuthService:
    return AuthService(db)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    return await auth_service.get_current_user(credentials.credentials)


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    return user


class RequireRole:
    """RBAC guard — usage: Depends(RequireRole(RoleEnum.ADMIN))"""

    def __init__(self, *allowed_roles: RoleEnum):
        self.allowed_roles = set(allowed_roles)

    def __call__(self, user: User = Depends(get_current_active_user)) -> User:
        if user.role not in self.allowed_roles and user.role != RoleEnum.SUPER_ADMIN:
            raise InsufficientPermissionsError(required=",".join(r.value for r in self.allowed_roles))
        return user


class RequirePermission:
    """PBAC guard backed by the database-driven permission catalog.

    Usage: Depends(RequirePermission("resume.delete"))
    Resolves role-derived + per-user permission overrides via AuthService.
    """

    def __init__(self, *required_permissions: str):
        self.required_permissions = set(required_permissions)

    async def __call__(
        self,
        user: User = Depends(get_current_active_user),
        auth_service: AuthService = Depends(get_auth_service),
    ) -> User:
        if user.role == RoleEnum.SUPER_ADMIN:
            return user
        effective = await auth_service.get_effective_permissions(user)
        if not self.required_permissions.issubset(effective):
            raise InsufficientPermissionsError(required=",".join(self.required_permissions))
        return user


def get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_user_agent(request: Request) -> str | None:
    return request.headers.get("User-Agent")


# --- Auth-endpoint rate limiters (Redis sliding window) ---
login_rate_limiter = SlidingWindowRateLimiter(
    key_prefix="login", limit=settings.LOGIN_RATE_LIMIT_PER_MINUTE, window_seconds=60
)
password_reset_rate_limiter = SlidingWindowRateLimiter(
    key_prefix="password_reset",
    limit=settings.PASSWORD_RESET_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)
email_verification_rate_limiter = SlidingWindowRateLimiter(
    key_prefix="email_verification",
    limit=settings.EMAIL_VERIFICATION_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)
