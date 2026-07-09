from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.email_comm.enums import (
    EmailAccountStatusEnum,
    EmailClassificationEnum,
    EmailFolderCategoryEnum,
    EmailProviderEnum,
    InterviewPlatformEnum,
    SyncJobStatusEnum,
    SyncTriggerEnum,
)


# --- Account connection ---

class GmailConnectRequest(BaseModel):
    authorization_code: str
    redirect_uri: str


class OutlookConnectRequest(BaseModel):
    authorization_code: str
    redirect_uri: str


class ImapConnectRequest(BaseModel):
    email_address: EmailStr
    password: str = Field(min_length=1)
    imap_host: str
    imap_port: int = 993
    imap_use_ssl: bool = True


class EmailAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: EmailProviderEnum
    email_address: str
    display_name: str | None
    status: EmailAccountStatusEnum
    last_synced_at: datetime | None
    error_message: str | None
    created_at: datetime


# --- Sync ---

class SyncTriggerRequest(BaseModel):
    trigger: SyncTriggerEnum = SyncTriggerEnum.MANUAL
    historical_days: int | None = Field(default=None, ge=1, le=365)


class EmailSyncJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    trigger: SyncTriggerEnum
    status: SyncJobStatusEnum
    messages_fetched: int
    messages_job_related: int
    messages_failed: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None


# --- Emails ---

class EmailListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    from_email: str
    from_name: str | None
    subject: str | None
    received_at: datetime
    is_read: bool
    is_job_related: bool
    ai_classification: EmailClassificationEnum | None
    confidence_score: float | None
    company_name: str | None
    job_title: str | None
    linked_application_id: str | None
    urgency: str | None


class EmailDetailResponse(EmailListItemResponse):
    thread_id: str | None
    body_clean: str | None
    ai_summary: str | None
    classification_reasoning: str | None
    extracted_entities: dict | None
    recruiter_name: str | None
    interview_type: str | None
    interview_datetime: datetime | None
    interview_duration_minutes: int | None
    interview_platform: InterviewPlatformEnum | None
    meeting_link: str | None
    assessment_link: str | None
    rejection_reason: str | None
    missing_skills: list[str] | None
    company_feedback: str | None
    match_confidence: float | None
    match_method: str | None


class EmailListFilters(BaseModel):
    is_job_related: bool | None = None
    classification: EmailClassificationEnum | None = None
    account_id: str | None = None
    linked_application_id: str | None = None
    folder_category: EmailFolderCategoryEnum | None = None
    search: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class EmailManualLinkRequest(BaseModel):
    application_id: str


class EmailThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    thread_id: str
    subject: str | None
    linked_application_id: str | None
    message_count: int
    last_message_at: datetime | None
    has_pending_follow_up: bool
    last_sender_was_recruiter: bool


class WebhookGmailNotification(BaseModel):
    """Body of a Gmail Pub/Sub push notification (base64-decoded envelope)."""

    email_address: str
    history_id: str


class WebhookOutlookNotification(BaseModel):
    """Single Microsoft Graph change-notification entry."""

    subscription_id: str
    resource: str
    change_type: str
