from fastapi import APIRouter, Depends, Request, status

from app.auth.dependencies import (
    email_verification_rate_limiter,
    get_auth_service,
    get_client_ip,
    get_current_active_user,
    get_user_agent,
    login_rate_limiter,
    password_reset_rate_limiter,
)
import secrets
import string
from datetime import timedelta

from app.auth.models import User
from app.auth.repositories import UserProfileRepository
from app.auth.schemas import (
    ForgotPasswordRequest,
    OverlayTokenResponse,
    OverlayValidateTokenRequest,
    OverlayValidateTokenResponse,
    PairingCodeResponse,
    ResetPasswordRequest,
    RevokeSessionRequest,
    SessionResponse,
    TokenPairResponse,
    TokenRefreshRequest,
    UserLoginRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
    UserRegisterRequest,
    UserResponse,
    VerifyEmailRequest,
)
from app.auth.services import AuthService
from app.core.database import get_db
from app.core.redis_client import get_redis
from app.core.security import create_access_token

router = APIRouter(prefix="/auth", tags=["Authentication"])

_PAIRING_CODE_ALPHABET = string.ascii_uppercase + string.digits
_PAIRING_CODE_TTL_SECONDS = 10 * 60  # 10 minutes
_OVERLAY_TOKEN_EXPIRES_DELTA = timedelta(days=90)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegisterRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    user = await auth_service.register(payload, ip_address=get_client_ip(request))
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenPairResponse, dependencies=[Depends(login_rate_limiter)])
async def login(
    payload: UserLoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenPairResponse:
    _, tokens = await auth_service.authenticate(
        payload, ip_address=get_client_ip(request), user_agent=get_user_agent(request)
    )
    return tokens


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh_token(
    payload: TokenRefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenPairResponse:
    return await auth_service.refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: TokenRefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.logout(payload.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.logout_all_devices(current_user.id)


@router.post("/verify-email", response_model=UserResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    user = await auth_service.verify_email(payload.token)
    return UserResponse.model_validate(user)


@router.post(
    "/resend-verification",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(email_verification_rate_limiter)],
)
async def resend_verification(
    payload: ForgotPasswordRequest,  # reuses {email} shape
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.resend_verification_email(payload.email)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(password_reset_rate_limiter)],
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.request_password_reset(payload.email)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.reset_password(payload.token, payload.new_password)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> list[SessionResponse]:
    sessions = await auth_service.list_sessions(current_user.id)
    return [SessionResponse.model_validate(s) for s in sessions]


@router.post("/revoke-session", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    payload: RevokeSessionRequest,
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    await auth_service.revoke_session(current_user.id, payload.session_id)


@router.get("/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(get_current_active_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.get("/me/profile", response_model=UserProfileResponse)
async def read_current_user_profile(
    current_user: User = Depends(get_current_active_user),
    db=Depends(get_db),
) -> UserProfileResponse:
    repo = UserProfileRepository(db)
    profile = await repo.get_by_user_id(current_user.id)
    if not profile:
        profile = await repo.create_default(current_user.id)
    return UserProfileResponse.model_validate(profile)


@router.put("/me/profile", response_model=UserProfileResponse)
async def update_current_user_profile(
    payload: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db=Depends(get_db),
) -> UserProfileResponse:
    repo = UserProfileRepository(db)
    profile = await repo.update(current_user.id, **payload.model_dump(exclude_unset=True))
    if not profile:
        profile = await repo.create_default(current_user.id)
    return UserProfileResponse.model_validate(profile)


# --- Overlay device pairing (bot-overlay) ---
# Flow: logged-in user requests a short-lived pairing code on the CareerOS
# website -> types that code into the desktop overlay -> overlay exchanges
# it (one-time) for a long-lived JWT scoped to "overlay_device", which it
# then stores locally and uses for all future authenticated requests.

@router.post("/overlay/generate-pairing-code", response_model=PairingCodeResponse)
async def generate_pairing_code(
    current_user: User = Depends(get_current_active_user),
) -> PairingCodeResponse:
    code = "".join(secrets.choice(_PAIRING_CODE_ALPHABET) for _ in range(8))
    redis = get_redis()
    await redis.set(f"pairing:{code}", str(current_user.id), ex=_PAIRING_CODE_TTL_SECONDS)
    return PairingCodeResponse(pairing_code=code)


@router.post("/overlay/validate-token", response_model=OverlayValidateTokenResponse)
async def validate_overlay_token(
    payload: OverlayValidateTokenRequest,
) -> OverlayValidateTokenResponse:
    redis = get_redis()
    key = f"pairing:{payload.token}"
    user_id = await redis.get(key)
    if not user_id:
        return OverlayValidateTokenResponse(valid=False)

    # One-time use: burn the code immediately so it can't be replayed.
    await redis.delete(key)

    token = create_access_token(
        user_id, extra_claims={"scope": "overlay_device"}, expires_delta=_OVERLAY_TOKEN_EXPIRES_DELTA
    )
    return OverlayValidateTokenResponse(valid=True, user_id=user_id, token=token)


@router.post("/overlay/regenerate-token", response_model=OverlayTokenResponse)
async def regenerate_overlay_token(
    current_user: User = Depends(get_current_active_user),
) -> OverlayTokenResponse:
    # Works off the overlay device's own (still-valid) JWT, same as any
    # other authenticated request - get_current_active_user doesn't care
    # about the "scope" claim, it just needs a valid access token.
    token = create_access_token(
        current_user.id, extra_claims={"scope": "overlay_device"}, expires_delta=_OVERLAY_TOKEN_EXPIRES_DELTA
    )
    return OverlayTokenResponse(token=token)
