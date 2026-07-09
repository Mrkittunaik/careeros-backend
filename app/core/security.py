import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=[settings.PASSWORD_HASH_SCHEME], deprecated="auto")

TokenType = Literal["access", "refresh"]


class TokenPayloadError(Exception):
    pass


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _key_and_secret(token_type: TokenType) -> tuple[str, timedelta]:
    if token_type == "access":
        return settings.JWT_SECRET_KEY, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return settings.JWT_REFRESH_SECRET_KEY, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def create_token(
    subject: str | UUID,
    token_type: TokenType,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    secret, default_expires_delta = _key_and_secret(token_type)
    expires_delta = expires_delta or default_expires_delta
    now = datetime.now(timezone.utc)
    to_encode: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("="),
    }
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, secret, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, token_type: TokenType) -> dict[str, Any]:
    secret, _ = _key_and_secret(token_type)
    try:
        payload = jwt.decode(token, secret, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise TokenPayloadError(str(exc)) from exc
    if payload.get("type") != token_type:
        raise TokenPayloadError("Invalid token type")
    return payload


def create_access_token(
    subject: str | UUID,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    return create_token(subject, "access", extra_claims, expires_delta)


def create_refresh_token(
    subject: str | UUID,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    return create_token(subject, "refresh", extra_claims, expires_delta)


# --- AES-256-GCM field-level encryption (for storing OAuth tokens, secrets, etc.) ---

def _derive_key() -> bytes:
    # Derive a 32-byte key deterministically from the configured secret.
    return hashlib.sha256(settings.AES_SECRET_KEY.encode("utf-8")).digest()


def encrypt_secret(plaintext: str) -> str:
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_secret(token: str) -> str:
    key = _derive_key()
    aesgcm = AESGCM(key)
    raw = base64.urlsafe_b64decode(token.encode("utf-8"))
    nonce, ciphertext = raw[:12], raw[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


# --- Opaque single-use tokens (email verification, password reset, refresh hash) ---
# Only the SHA-256 hash is ever persisted; the raw token is emailed/returned once
# and never stored, so a DB leak alone cannot be used to impersonate a user.

def generate_secure_token(num_bytes: int = 32) -> str:
    return base64.urlsafe_b64encode(os.urandom(num_bytes)).decode("utf-8").rstrip("=")


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
