import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.exceptions import (
    AccountLockedError,
    EmailAlreadyVerifiedError,
    EmailNotVerifiedError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    SessionNotFoundError,
    TokenRevokedError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.auth.mail import MailService
from app.auth.models import AuthActionEnum, RoleEnum, Session, SessionStatusEnum, User
from app.auth.repositories import (
    AuditLogRepository,
    EmailVerificationRepository,
    PasswordResetRepository,
    PermissionRepository,
    SessionRepository,
    UserProfileRepository,
    UserRepository,
)
from app.auth.schemas import (
    TokenPairResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.core.config import settings
from app.core.security import (
    TokenPayloadError,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_secure_token,
    hash_password,
    hash_token,
    verify_password,
)

logger = logging.getLogger("app.auth.services")


class AuthService:
    """Orchestrates registration, verification, login/lockout, token
    rotation, session lifecycle, and password reset. Pure business logic —
    no HTTP concerns, no dependency on job/automation/email/AI modules.

    Backed entirely by MongoDB. Every repository call writes immediately
    (no separate "commit" step the way SQLAlchemy needed).
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.email_tokens = EmailVerificationRepository(db)
        self.reset_tokens = PasswordResetRepository(db)
        self.permissions = PermissionRepository(db)
        self.profiles = UserProfileRepository(db)
        self.audit = AuditLogRepository(db)

    # ------------------------------------------------------------------ #
    # Registration & email verification
    # ------------------------------------------------------------------ #

    async def register(self, payload: UserRegisterRequest, ip_address: str | None) -> User:
        existing = await self.users.get_by_email(payload.email)
        if existing:
            raise UserAlreadyExistsError(payload.email)

        user = await self.users.create(
            full_name=payload.full_name,
            email=payload.email.lower(),
            password_hash=hash_password(payload.password),
            phone=payload.phone,
            role=RoleEnum.USER,
            is_verified=False,
        )
        await self.profiles.create_default(user.id)
        await self.audit.log(
            AuthActionEnum.REGISTER, "success", user_id=user.id, ip_address=ip_address
        )

        await self._issue_email_verification(user)
        logger.info("user_registered", extra={"user_id": user.id})
        return user

    async def _issue_email_verification(self, user: User) -> None:
        raw_token = generate_secure_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES
        )
        await self.email_tokens.create(user.id, hash_token(raw_token), expires_at)
        await self.audit.log(AuthActionEnum.EMAIL_VERIFICATION_SENT, "success", user_id=user.id)
        MailService.queue_verification_email(user.email, user.full_name, raw_token)

    async def resend_verification_email(self, email: str) -> None:
        user = await self.users.get_by_email(email)
        if not user:
            # Do not leak account existence.
            return
        if user.is_verified:
            raise EmailAlreadyVerifiedError()
        await self.email_tokens.invalidate_all_for_user(user.id)
        await self._issue_email_verification(user)

    async def verify_email(self, raw_token: str) -> User:
        token_hash = hash_token(raw_token)
        record = await self.email_tokens.get_by_hash(token_hash)
        if not record or record.used_at is not None:
            raise InvalidTokenError("Verification token is invalid or already used.")
        if record.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError("Verification token has expired.")

        user = await self.users.get_by_id(record.user_id)
        if not user:
            raise UserNotFoundError(record.user_id)
        if user.is_verified:
            raise EmailAlreadyVerifiedError()

        await self.users.mark_verified(user.id)
        await self.email_tokens.mark_used(record.id)
        await self.audit.log(AuthActionEnum.EMAIL_VERIFIED, "success", user_id=user.id)
        return user

    # ------------------------------------------------------------------ #
    # Login / lockout / logout
    # ------------------------------------------------------------------ #

    async def authenticate(
        self, payload: UserLoginRequest, ip_address: str | None, user_agent: str | None = None
    ) -> tuple[User, TokenPairResponse]:
        user = await self.users.get_by_email(payload.email)

        if not user or not user.password_hash:
            # Constant-shape failure: don't distinguish "no such user" from "bad password".
            await self.audit.log(
                AuthActionEnum.LOGIN_FAILED, "failure", ip_address=ip_address,
                metadata={"email": payload.email, "reason": "no_such_user"},
            )
            raise InvalidCredentialsError()

        if user.is_locked:
            if user.locked_until and user.locked_until > datetime.now(timezone.utc):
                await self.audit.log(
                    AuthActionEnum.LOGIN_FAILED, "failure", user_id=user.id, ip_address=ip_address,
                    metadata={"reason": "account_locked"},
                )
                raise AccountLockedError(unlock_at=user.locked_until.isoformat())
            # Lock window elapsed — auto-unlock and continue.
            await self.users.unlock_account(user.id)
            user.is_locked = False
            user.failed_login_count = 0

        if not user.is_active:
            raise InactiveUserError()

        if not verify_password(payload.password, user.password_hash):
            await self._register_failed_attempt(user, ip_address)
            raise InvalidCredentialsError()

        if not user.is_verified:
            raise EmailNotVerifiedError()

        # Successful login resets the failure counter.
        if user.failed_login_count:
            await self.users.register_failed_login(user.id, 0)

        session_record = await self._create_session(user, payload, ip_address, user_agent)
        tokens = await self._issue_token_pair(user, session_record)

        await self.users.update_last_login(user.id)
        await self.audit.log(
            AuthActionEnum.LOGIN_SUCCESS, "success", user_id=user.id, ip_address=ip_address,
            device_id=payload.device_id,
        )
        return user, tokens

    async def _register_failed_attempt(self, user: User, ip_address: str | None) -> None:
        new_count = user.failed_login_count + 1
        await self.users.register_failed_login(user.id, new_count)
        await self.audit.log(
            AuthActionEnum.LOGIN_FAILED, "failure", user_id=user.id, ip_address=ip_address,
            metadata={"failed_count": new_count},
        )
        if new_count >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            unlock_at = datetime.now(timezone.utc) + timedelta(
                minutes=settings.ACCOUNT_LOCK_DURATION_MINUTES
            )
            await self.users.lock_account(user.id, unlock_at)
            await self.audit.log(
                AuthActionEnum.ACCOUNT_LOCKED, "success", user_id=user.id, ip_address=ip_address,
                metadata={"unlock_at": unlock_at.isoformat()},
            )

    async def _create_session(
        self, user: User, payload: UserLoginRequest, ip_address: str | None, user_agent: str | None
    ) -> Session:
        device_id = payload.device_id or generate_secure_token(16)
        # Placeholder hash; replaced with the real refresh token hash once minted.
        return await self.sessions.create(
            user_id=user.id,
            device_id=device_id,
            device_name=payload.device_name,
            os_name=payload.os_name,
            browser=payload.browser,
            ip_address=ip_address,
            user_agent=user_agent,
            refresh_token_hash="pending",
            refresh_token_jti="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )

    async def refresh(self, refresh_token: str) -> TokenPairResponse:
        try:
            payload = decode_token(refresh_token, "refresh")
        except TokenPayloadError as exc:
            raise InvalidTokenError(str(exc)) from exc

        jti = payload.get("jti")
        record = await self.sessions.get_by_jti(jti) if jti else None
        if not record:
            raise InvalidTokenError("Refresh token not recognized.")
        if record.status != SessionStatusEnum.ACTIVE:
            raise TokenRevokedError()
        if record.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError("Refresh token expired.")
        if record.refresh_token_hash != hash_token(refresh_token):
            raise InvalidTokenError("Refresh token does not match session record.")

        user = await self.users.get_by_id(record.user_id)
        if not user or not user.is_active:
            raise InactiveUserError()

        # Rotate: mint a fresh pair, persist onto the same session row.
        access_token = create_access_token(user.id, extra_claims={"role": user.role.value})
        new_refresh_token = create_refresh_token(user.id)
        new_payload = decode_token(new_refresh_token, "refresh")

        await self.sessions.update_tokens(
            record.id,
            refresh_token_hash=hash_token(new_refresh_token),
            refresh_token_jti=new_payload["jti"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )

        await self.audit.log(AuthActionEnum.TOKEN_REFRESH, "success", user_id=user.id)

        return TokenPairResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def logout(self, refresh_token: str) -> None:
        try:
            payload = decode_token(refresh_token, "refresh")
        except TokenPayloadError:
            return
        jti = payload.get("jti")
        if jti:
            record = await self.sessions.get_by_jti(jti)
            await self.sessions.revoke_by_jti(jti)
            if record:
                await self.audit.log(AuthActionEnum.LOGOUT, "success", user_id=record.user_id)

    async def logout_all_devices(self, user_id: str) -> None:
        await self.sessions.revoke_all_for_user(user_id)
        await self.audit.log(AuthActionEnum.LOGOUT_ALL, "success", user_id=user_id)

    # ------------------------------------------------------------------ #
    # Sessions / devices
    # ------------------------------------------------------------------ #

    async def list_sessions(self, user_id: str) -> list[Session]:
        return await self.sessions.list_active_for_user(user_id)

    async def revoke_session(self, user_id: str, session_id: str) -> None:
        record = await self.sessions.get_by_id(session_id)
        if not record or record.user_id != user_id:
            raise SessionNotFoundError(str(session_id))
        await self.sessions.revoke(session_id)
        await self.audit.log(AuthActionEnum.SESSION_REVOKED, "success", user_id=user_id)

    # ------------------------------------------------------------------ #
    # Password reset
    # ------------------------------------------------------------------ #

    async def request_password_reset(self, email: str) -> None:
        user = await self.users.get_by_email(email)
        if not user:
            return  # Never reveal whether an account exists.

        raw_token = generate_secure_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
        )
        await self.reset_tokens.create(user.id, hash_token(raw_token), expires_at)
        await self.audit.log(AuthActionEnum.PASSWORD_RESET_REQUESTED, "success", user_id=user.id)
        MailService.queue_password_reset_email(user.email, user.full_name, raw_token)

    async def reset_password(self, raw_token: str, new_password: str) -> None:
        token_hash = hash_token(raw_token)
        record = await self.reset_tokens.get_by_hash(token_hash)
        if not record or record.used_at is not None:
            raise InvalidTokenError("Reset token is invalid or already used.")
        if record.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError("Reset token has expired.")

        user = await self.users.get_by_id(record.user_id)
        if not user:
            raise UserNotFoundError(record.user_id)

        await self.users.set_password(user.id, hash_password(new_password))
        await self.reset_tokens.mark_used(record.id)
        # Invalidate all sessions after a password reset, per spec.
        await self.sessions.revoke_all_for_user(user.id)
        await self.audit.log(AuthActionEnum.PASSWORD_RESET_COMPLETED, "success", user_id=user.id)

    # ------------------------------------------------------------------ #
    # Current user / permission resolution
    # ------------------------------------------------------------------ #

    async def get_current_user(self, access_token: str) -> User:
        try:
            payload = decode_token(access_token, "access")
        except TokenPayloadError as exc:
            raise InvalidTokenError(str(exc)) from exc

        user_id = payload.get("sub")
        if not user_id:
            raise InvalidTokenError("Malformed token payload.")

        user = await self.users.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id)
        if not user.is_active:
            raise InactiveUserError()
        return user

    async def get_effective_permissions(self, user: User) -> set[str]:
        return await self.permissions.get_effective_permissions(user.id, user.role)

    async def _issue_token_pair(self, user: User, session_record: Session) -> TokenPairResponse:
        access_token = create_access_token(user.id, extra_claims={"role": user.role.value})
        refresh_token = create_refresh_token(user.id)
        refresh_payload = decode_token(refresh_token, "refresh")

        await self.sessions.update_tokens(
            session_record.id,
            refresh_token_hash=hash_token(refresh_token),
            refresh_token_jti=refresh_payload["jti"],
            expires_at=session_record.expires_at,
        )

        return TokenPairResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
