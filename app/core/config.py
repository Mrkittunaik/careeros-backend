from functools import lru_cache
from typing import List, Optional

from pydantic import Field, PostgresDsn, RedisDsn, AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- App ---
    PROJECT_NAME: str = "CareerOS AI"
    ENVIRONMENT: str = Field(default="development")
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # --- Security ---
    JWT_SECRET_KEY: str
    JWT_REFRESH_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    AES_SECRET_KEY: str  # 32-byte key, base64 or hex encoded, used for field-level encryption
    PASSWORD_HASH_SCHEME: str = "bcrypt"

    # --- Account lockout / brute-force protection ---
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCK_DURATION_MINUTES: int = 30
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10
    PASSWORD_RESET_RATE_LIMIT_PER_HOUR: int = 3
    EMAIL_VERIFICATION_RATE_LIMIT_PER_HOUR: int = 5

    # --- Verification / reset token lifetimes ---
    EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES: int = 30
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 20

    # --- Outbound email / frontend links ---
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    MAIL_FROM_ADDRESS: str = "noreply@dmflowapp.in"
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

    # --- CORS ---
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # --- Database (MongoDB — see below) ---

    # --- Redis / Celery ---
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def _default_broker(cls, v, info):
        return v

    # --- Object Storage (MinIO/S3) ---
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET_RESUMES: str = "resumes"
    MINIO_SECURE: bool = False

    # --- MongoDB (shared default cluster; users on paid plans may connect
    # their own instead -- see app.integrations) ---
    MONGO_DEFAULT_URI: str = "mongodb://localhost:27017"
    MONGO_DEFAULT_DB_NAME: str = "careeros"

    # --- API quota (per user, resets daily/monthly) ---
    # PREMIUM_USER / ENTERPRISE_USER / SUPER_ADMIN roles are exempt and may
    # also connect their own MongoDB via app.integrations.
    QUOTA_FREE_DAILY_CALLS: int = 200
    QUOTA_FREE_MONTHLY_CALLS: int = 3000

    # --- Vector DB ---
    CHROMADB_HOST: str = "localhost"
    CHROMADB_PORT: int = 8001
    CHROMADB_COLLECTION: str = "resume_embeddings"

    # --- AI Providers ---
    GROQ_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: Optional[str] = "http://localhost:11434"
    AI_PROVIDER_PRIORITY: List[str] = ["groq", "openai", "gemini", "claude", "ollama"]
    AI_REQUEST_TIMEOUT_SECONDS: int = 30
    AI_MAX_RETRIES_PER_PROVIDER: int = 2

    # --- Resume module ---
    RESUME_MAX_FILE_SIZE_MB: int = 10
    RESUME_ALLOWED_EXTENSIONS: List[str] = ["pdf", "docx"]
    RESUME_MAX_PER_USER: int = 50

    @field_validator("AI_PROVIDER_PRIORITY", mode="before")
    @classmethod
    def _split_providers(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # --- OAuth2 ---
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[AnyHttpUrl] = None
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GITHUB_REDIRECT_URI: Optional[AnyHttpUrl] = None

    # --- Email Intelligence (Part 6) ---
    OUTLOOK_CLIENT_ID: Optional[str] = None
    OUTLOOK_CLIENT_SECRET: Optional[str] = None
    OUTLOOK_WEBHOOK_NOTIFICATION_URL: Optional[str] = None
    OUTLOOK_WEBHOOK_CLIENT_STATE: Optional[str] = None
    GMAIL_PUBSUB_TOPIC: Optional[str] = None
    EMAIL_SYNC_POLL_INTERVAL_MINUTES: int = 15
    EMAIL_HISTORICAL_IMPORT_DAYS: int = 90

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True


@lru_cache
def get_settings() -> "Settings":
    return Settings()


settings = get_settings()
