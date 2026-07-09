from datetime import timedelta

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
from app.auth.models import User
from app.auth.repositories import UserProfileRepository
from app.auth.schemas import (
    ForgotPasswordRequest,
    OverlayTokenResponse,
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
from app.core.security import create_access_token

router = APIRouter(prefix="/auth", tags=["Authentication"])

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


# --- Overlay device key (bot-overlay) ---
# Flow: logged-in user clicks "Generate bot key" on the CareerOS website ->
# backend returns a long-lived JWT scoped to "overlay_device" -> user
# copies it and pastes it into the bot, which stores it locally and uses
# it for every request from then on. No pairing code, no expiry timer -
# it's a straight generate-and-copy key, permanent until regenerated.

@router.post("/overlay/generate-key", response_model=OverlayTokenResponse)
async def generate_overlay_key(
    current_user: User = Depends(get_current_active_user),
) -> OverlayTokenResponse:
    token = create_access_token(
        current_user.id, extra_claims={"scope": "overlay_device"}, expires_delta=_OVERLAY_TOKEN_EXPIRES_DELTA
    )
    return OverlayTokenResponse(token=token)


@router.post("/overlay/regenerate-key", response_model=OverlayTokenResponse)
async def regenerate_overlay_key(
    current_user: User = Depends(get_current_active_user),
) -> OverlayTokenResponse:
    # Works off the overlay device's own (still-valid) JWT, same as any
    # other authenticated request - get_current_active_user doesn't care
    # about the "scope" claim, it just needs a valid access token. Old key
    # simply stops being used once the bot switches to the new one; it's
    # not actively revoked (matches "regenerate anytime" behavior).
    token = create_access_token(
        current_user.id, extra_claims={"scope": "overlay_device"}, expires_delta=_OVERLAY_TOKEN_EXPIRES_DELTA
    )
    return OverlayTokenResponse(token=token)
