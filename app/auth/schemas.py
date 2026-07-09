import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.auth.models import RoleEnum, SessionStatusEnum


def _validate_password_strength(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one digit.")
    if not any(c in "!@#$%^&*()-_=+[]{};:,.<>?/" for c in v):
        raise ValueError("Password must contain at least one special character.")
    return v


class UserRegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str
    device_id: str | None = None
    device_name: str | None = None
    os_name: str | None = None
    browser: str | None = None


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class VerifyEmailRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class RevokeSessionRequest(BaseModel):
    session_id: uuid.UUID


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: EmailStr
    phone: str | None = None
    role: RoleEnum
    is_verified: bool
    is_active: bool
    is_locked: bool
    profile_completed: bool
    created_at: datetime
    last_login: datetime | None = None


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: str
    device_name: str | None
    os_name: str | None
    browser: str | None
    ip_address: str | None
    location: str | None
    status: SessionStatusEnum
    last_active_at: datetime
    expires_at: datetime
    created_at: datetime


class UserProfileUpdateRequest(BaseModel):
    current_title: str | None = None
    experience_years: int | None = Field(default=None, ge=0, le=60)
    skills: list[str] | None = None
    education: list[dict] | None = None
    resume_preferences: dict | None = None
    preferred_roles: list[str] | None = None
    preferred_locations: list[str] | None = None
    salary_expectation: str | None = None
    work_mode: str | None = Field(default=None, pattern="^(remote|hybrid|onsite)$")
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


# --- Overlay device pairing (bot-overlay) ---

class PairingCodeResponse(BaseModel):
    pairing_code: str


class OverlayValidateTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=64)


class OverlayValidateTokenResponse(BaseModel):
    valid: bool
    user_id: str | None = None
    token: str | None = None


class OverlayTokenResponse(BaseModel):
    token: str


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    current_title: str | None
    experience_years: int | None
    skills: list[str]
    education: list[dict]
    resume_preferences: dict
    preferred_roles: list[str]
    preferred_locations: list[str]
    salary_expectation: str | None
    work_mode: str | None
    linkedin_url: str | None
    github_url: str | None
    portfolio_url: str | None
