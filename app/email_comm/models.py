"""Email Communication module — MongoDB documents.

Converted from SQLAlchemy/Postgres (old version kept as
models.py.postgres.bak). Four collections, matching the original tables
one-to-one: EmailAccount, Email, EmailThread, EmailSyncJob are each kept
as their own collection (not embedded into one another), because every
one of them is queried independently and/or at volume:
  - Email is searched/paginated/filtered across many fields regardless
    of account (EmailQueryService.list_emails), so it can't be nested
    under EmailAccount.
  - EmailThread is looked up by (account_id, thread_id) on nearly every
    ingested message and needs its own indexed collection.
  - EmailSyncJob can accumulate many rows per account (one per sync run)
    and is listed/paginated on its own.
This mirrors the ActivityLogEntry precedent from app.autoapply: separate
collection + plain string foreign keys rather than an embedded list.
"""

from datetime import datetime

from pydantic import Field

from app.core.mongo_base import MongoDocument
from app.email_comm.enums import (
    EmailAccountStatusEnum,
    EmailClassificationEnum,
    EmailFolderCategoryEnum,
    EmailProviderEnum,
    InterviewPlatformEnum,
    SyncJobStatusEnum,
    SyncTriggerEnum,
)


class EmailAccount(MongoDocument):
    """A connected Gmail / Outlook / IMAP mailbox belonging to a user.
    Collection: email_accounts.

    OAuth tokens (Gmail/Outlook) or IMAP passwords are stored encrypted at
    rest via app.core.security.encrypt_secret/decrypt_secret — never in
    plaintext, per the spec's Security Rules. The old table's
    UniqueConstraint(user_id, email_address) is now enforced at the
    application layer (EmailAccountRepository.get_by_address check before
    create) plus a unique index — see app.coreindexing / migration notes.
    """

    user_id: str
    provider: EmailProviderEnum
    email_address: str
    display_name: str | None = None

    # OAuth (Gmail / Outlook) — encrypted at rest.
    encrypted_access_token: str | None = None
    encrypted_refresh_token: str | None = None
    token_expires_at: datetime | None = None
    oauth_scope: str | None = None

    # IMAP — encrypted at rest.
    imap_host: str | None = None
    imap_port: int | None = None
    imap_use_ssl: bool = True
    encrypted_imap_password: str | None = None

    status: EmailAccountStatusEnum = EmailAccountStatusEnum.CONNECTED
    last_synced_at: datetime | None = None
    history_id: str | None = None  # Gmail historyId cursor
    delta_link: str | None = None  # Outlook Graph delta cursor
    webhook_channel_id: str | None = None
    webhook_expires_at: datetime | None = None
    error_message: str | None = None
    consecutive_error_count: int = 0


class Email(MongoDocument):
    """A single ingested email, per the spec's Email Entity Design.
    Collection: emails.
    """

    user_id: str
    account_id: str
    provider: EmailProviderEnum

    message_id: str
    thread_id: str | None = None
    body_hash: str  # sha256, duplicate detection

    from_email: str
    from_name: str | None = None
    to_email: str | None = None
    subject: str | None = None

    body_raw: str | None = None
    body_clean: str | None = None

    received_at: datetime
    is_read: bool = False

    folder_category: EmailFolderCategoryEnum | None = None
    is_job_related: bool = False

    # --- AI classification output ---
    ai_classification: EmailClassificationEnum | None = None
    confidence_score: float | None = None
    classification_reasoning: str | None = None
    extracted_entities: dict | None = None
    urgency: str | None = None  # low/medium/high
    ai_summary: str | None = None

    # --- Recruiter / role metadata extracted from the email ---
    recruiter_name: str | None = None
    company_name: str | None = None
    job_title: str | None = None

    # --- Interview intelligence ---
    interview_type: str | None = None
    interview_datetime: datetime | None = None
    interview_duration_minutes: int | None = None
    interview_platform: InterviewPlatformEnum | None = None
    meeting_link: str | None = None
    assessment_link: str | None = None

    # --- Rejection intelligence ---
    rejection_reason: str | None = None
    missing_skills: list[str] | None = None
    company_feedback: str | None = None

    # --- Linking / matching ---
    linked_application_id: str | None = None
    match_confidence: float | None = None
    match_method: str | None = None  # exact/fuzzy/semantic/manual

    status_applied: bool = False
    processed_at: datetime | None = None
    processing_error: str | None = None


class EmailThread(MongoDocument):
    """Denormalized thread rollup for fast chronological rendering, per the
    spec's Email Thread Tracking section. Collection: email_threads.
    """

    user_id: str
    account_id: str
    thread_id: str
    subject: str | None = None
    linked_application_id: str | None = None
    message_count: int = 0
    last_message_at: datetime | None = None
    has_pending_follow_up: bool = False
    last_sender_was_recruiter: bool = False


class EmailSyncJob(MongoDocument):
    """One execution of a mailbox sync (initial import, scheduled poll, or
    webhook-triggered delta), per the spec's Real-Time Email Monitoring and
    Email Queue System sections. Collection: email_sync_jobs.
    """

    user_id: str
    account_id: str
    trigger: SyncTriggerEnum
    status: SyncJobStatusEnum = SyncJobStatusEnum.PENDING
    messages_fetched: int = 0
    messages_job_related: int = 0
    messages_failed: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
