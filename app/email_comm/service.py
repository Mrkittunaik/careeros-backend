"""Email Communication module service layer — MongoDB version.

Converted from SQLAlchemy/Postgres (old version kept as
service.py.postgres.bak). All business logic, validation rules, and
exception behavior are kept identical to the original. The only
structural change is that there's no more `self.session` +
commit/rollback transaction — every repository method is already a
single atomic Motor operation, so calls that used to be
"stage change, then commit" are now just "stage change" (the write has
already happened once the repository call returns). Where the old code
rolled back on failure (mid-sync error handling), the Mongo version
simply doesn't apply the partial update, since nothing was staged
in-memory to roll back in the first place.
"""

import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ai_core.email_analysis import EmailAnalysisEngine
from app.application.enums import ApplicationStatusEnum
from app.application.service import ApplicationService
from app.core.security import decrypt_secret, encrypt_secret
from app.email_comm.constants import DEFAULT_HISTORICAL_IMPORT_DAYS, MAX_EMAILS_PER_SYNC_BATCH
from app.email_comm.enums import (
    CLASSIFICATION_TO_APPLICATION_STATUS,
    EmailAccountStatusEnum,
    EmailClassificationEnum,
    EmailProviderEnum,
    NON_REGRESSIVE_CLASSIFICATIONS,
    SyncJobStatusEnum,
    SyncTriggerEnum,
)
from app.email_comm.exceptions import (
    EmailAccountAccessDeniedError,
    EmailAccountAlreadyConnectedError,
    EmailAccountNotFoundError,
    EmailNotFoundError,
)
from app.email_comm.filters import body_hash, classify_folder_category, should_run_ai_classification
from app.email_comm.matching import EmailApplicationMatcher
from app.email_comm.providers import build_client
from app.email_comm.providers.base import RawEmailMessage
from app.email_comm.providers.gmail import exchange_authorization_code as gmail_exchange
from app.email_comm.providers.outlook import exchange_authorization_code as outlook_exchange
from app.email_comm.repository import EmailAccountRepository, EmailRepository, EmailSyncJobRepository, EmailThreadRepository

logger = logging.getLogger("app.email_comm.service")


class EmailAccountService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = EmailAccountRepository(db)

    async def connect_gmail(self, user_id: str, *, authorization_code: str, redirect_uri: str):
        token_data = await gmail_exchange(code=authorization_code, redirect_uri=redirect_uri)
        email_address = token_data.get("email") or token_data.get("id_token_email") or "unknown@gmail.com"
        return await self._create_oauth_account(
            user_id,
            provider=EmailProviderEnum.GMAIL,
            email_address=email_address,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_in=token_data.get("expires_in", 3600),
            scope=token_data.get("scope"),
        )

    async def connect_outlook(self, user_id: str, *, authorization_code: str, redirect_uri: str):
        token_data = await outlook_exchange(code=authorization_code, redirect_uri=redirect_uri)
        email_address = token_data.get("email") or "unknown@outlook.com"
        return await self._create_oauth_account(
            user_id,
            provider=EmailProviderEnum.OUTLOOK,
            email_address=email_address,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_in=token_data.get("expires_in", 3600),
            scope=token_data.get("scope"),
        )

    async def _create_oauth_account(
        self, user_id: str, *, provider: EmailProviderEnum, email_address: str, access_token: str,
        refresh_token: str | None, expires_in: int, scope: str | None,
    ):
        existing = await self.repo.get_by_address(user_id, email_address)
        if existing:
            raise EmailAccountAlreadyConnectedError(email_address)

        account = await self.repo.create(
            user_id=user_id,
            provider=provider,
            email_address=email_address,
            encrypted_access_token=encrypt_secret(access_token),
            encrypted_refresh_token=encrypt_secret(refresh_token) if refresh_token else None,
            token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            oauth_scope=scope,
            status=EmailAccountStatusEnum.CONNECTED,
        )
        return account

    async def connect_imap(
        self, user_id: str, *, email_address: str, password: str, imap_host: str, imap_port: int, imap_use_ssl: bool
    ):
        existing = await self.repo.get_by_address(user_id, email_address)
        if existing:
            raise EmailAccountAlreadyConnectedError(email_address)

        account = await self.repo.create(
            user_id=user_id,
            provider=EmailProviderEnum.IMAP,
            email_address=email_address,
            imap_host=imap_host,
            imap_port=imap_port,
            imap_use_ssl=imap_use_ssl,
            encrypted_imap_password=encrypt_secret(password),
            status=EmailAccountStatusEnum.CONNECTED,
        )
        return account

    async def list_accounts(self, user_id: str):
        return await self.repo.list_for_user(user_id)

    async def disconnect(self, user_id: str, account_id: str) -> None:
        account = await self._get_owned_or_raise(account_id, user_id)
        await self.repo.soft_delete(account.id)

    async def _get_owned_or_raise(self, account_id: str, user_id: str):
        account = await self.repo.get_by_id(account_id)
        if not account:
            raise EmailAccountNotFoundError(str(account_id))
        if account.user_id != str(user_id):
            raise EmailAccountAccessDeniedError()
        return account


class EmailIngestionService:
    """Runs the full Email Ingestion Flow for one account: sync -> filter ->
    extract -> store -> AI classify -> match/update application status.
    Invoked from Celery tasks (app.email_comm.tasks), never directly from a
    request handler (sync can take a while for historical imports).
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.account_repo = EmailAccountRepository(db)
        self.email_repo = EmailRepository(db)
        self.thread_repo = EmailThreadRepository(db)
        self.job_repo = EmailSyncJobRepository(db)

    async def sync_account(
        self, account_id: str, *, trigger: SyncTriggerEnum, historical_days: int | None = None
    ) -> str:
        account = await self.account_repo.get_by_id(account_id)
        if not account:
            raise EmailAccountNotFoundError(str(account_id))

        job = await self.job_repo.create(user_id=account.user_id, account_id=account.id, trigger=trigger)

        await self.job_repo.mark_running(job.id)
        await self.account_repo.update_fields(account.id, status=EmailAccountStatusEnum.SYNCING)

        fetched = job_related = failed = 0
        try:
            client = await self._build_authenticated_client(account)
            since = None
            cursor = account.history_id if account.provider == EmailProviderEnum.GMAIL else account.delta_link
            if trigger == SyncTriggerEnum.INITIAL_IMPORT or not cursor:
                since = datetime.now(timezone.utc) - timedelta(days=historical_days or DEFAULT_HISTORICAL_IMPORT_DAYS)
                cursor = None

            messages, next_cursor = await client.fetch_messages(since=since, cursor=cursor, limit=MAX_EMAILS_PER_SYNC_BATCH)
            fetched = len(messages)

            for message in messages:
                try:
                    was_ingested = await self._ingest_message(account, message)
                    if was_ingested:
                        job_related += 1
                except Exception:  # noqa: BLE001
                    failed += 1
                    logger.exception("email_ingest_message_failed", extra={"account_id": str(account.id)})

            update_fields = {"status": EmailAccountStatusEnum.CONNECTED, "last_synced_at": datetime.now(timezone.utc), "consecutive_error_count": 0}
            if account.provider == EmailProviderEnum.GMAIL:
                update_fields["history_id"] = next_cursor
            elif account.provider == EmailProviderEnum.OUTLOOK:
                update_fields["delta_link"] = next_cursor
            await self.account_repo.update_fields(account.id, **update_fields)

            await self.job_repo.mark_completed(job.id, fetched=fetched, job_related=job_related, failed=failed)
        except Exception as exc:  # noqa: BLE001
            await self.account_repo.update_fields(
                account.id,
                status=EmailAccountStatusEnum.ERROR,
                error_message=str(exc)[:1000],
                consecutive_error_count=account.consecutive_error_count + 1,
            )
            await self.job_repo.mark_failed(job.id, error_message=str(exc)[:1000])
            raise

        return job.id

    async def _build_authenticated_client(self, account):
        access_token = decrypt_secret(account.encrypted_access_token) if account.encrypted_access_token else None
        refresh_token = decrypt_secret(account.encrypted_refresh_token) if account.encrypted_refresh_token else None
        imap_password = decrypt_secret(account.encrypted_imap_password) if account.encrypted_imap_password else None

        client = build_client(account, access_token=access_token or "", refresh_token=refresh_token, imap_password=imap_password)

        if account.provider in (EmailProviderEnum.GMAIL, EmailProviderEnum.OUTLOOK):
            if account.token_expires_at and account.token_expires_at <= datetime.now(timezone.utc) + timedelta(minutes=5):
                new_token, expires_at = await client.refresh_access_token()
                await self.account_repo.update_fields(
                    account.id, encrypted_access_token=encrypt_secret(new_token), token_expires_at=expires_at
                )
        return client

    async def _ingest_message(self, account, message: RawEmailMessage) -> bool:
        # --- Duplicate detection (message_id, then body hash) ---
        if await self.email_repo.exists_by_message_id(account.id, message.message_id):
            return False
        hashed = body_hash(message.subject, message.body_clean, message.from_email)
        if await self.email_repo.exists_by_body_hash(account.id, hashed):
            return False

        category = classify_folder_category(message)
        is_job_related = should_run_ai_classification(category)

        email_row = await self.email_repo.create(
            user_id=account.user_id,
            account_id=account.id,
            provider=account.provider,
            message_id=message.message_id,
            thread_id=message.thread_id,
            body_hash=hashed,
            from_email=message.from_email,
            from_name=message.from_name,
            to_email=message.to_email,
            subject=message.subject,
            body_raw=message.body_raw,
            body_clean=message.body_clean,
            received_at=message.received_at,
            is_read=message.is_read,
            folder_category=category,
            is_job_related=is_job_related,
        )

        thread_row = None
        if message.thread_id:
            thread_row = await self.thread_repo.get_or_create(
                user_id=account.user_id, account_id=account.id, thread_id=message.thread_id, subject=message.subject
            )

        if is_job_related:
            await self._classify_and_link(account, email_row, thread_row)
        else:
            await self.email_repo.update_fields(email_row.id, processed_at=datetime.now(timezone.utc))

        if thread_row:
            await self.thread_repo.bump(thread_row.id, last_message_at=message.received_at, is_recruiter=is_job_related)

        return is_job_related

    async def _classify_and_link(self, account, email_row, thread_row) -> None:
        engine = EmailAnalysisEngine(self.db, user_id=account.user_id)
        try:
            analysis = await engine.analyze(email_row.body_clean or email_row.subject or "", source_email_id=email_row.id)
        except Exception as exc:  # noqa: BLE001
            await self.email_repo.update_fields(
                email_row.id, processing_error=str(exc)[:1000], processed_at=datetime.now(timezone.utc)
            )
            return

        classification = _map_ai_status_to_classification(analysis.status_classification.value)

        await self.email_repo.update_fields(
            email_row.id,
            ai_classification=classification,
            confidence_score=analysis.confidence_score,
            recruiter_name=analysis.recruiter_name,
            company_name=analysis.company_name,
            job_title=analysis.job_title,
            interview_type=analysis.interview_type.value if analysis.interview_type else None,
            interview_datetime=analysis.interview_datetime,
            interview_duration_minutes=analysis.duration_minutes,
            meeting_link=analysis.meeting_link,
            rejection_reason=analysis.rejection_reason,
            missing_skills=analysis.missing_skills,
            company_feedback=analysis.feedback,
            processed_at=datetime.now(timezone.utc),
        )

        matcher = EmailApplicationMatcher(self.db)
        application, confidence, method = await matcher.find_match(
            user_id=account.user_id,
            company_name=analysis.company_name,
            job_title=analysis.job_title,
            thread_linked_application_id=thread_row.linked_application_id if thread_row else None,
        )

        if not application:
            return

        await self.email_repo.update_fields(
            email_row.id, linked_application_id=application.id, match_confidence=confidence, match_method=method
        )
        if thread_row:
            await self.thread_repo.link_application(thread_row.id, application.id)

        new_status_value = CLASSIFICATION_TO_APPLICATION_STATUS.get(classification.value)
        if not new_status_value:
            return
        new_status = ApplicationStatusEnum(new_status_value)

        if classification.value in NON_REGRESSIVE_CLASSIFICATIONS and EmailApplicationMatcher.is_regression(
            application.status, new_status
        ):
            return
        if application.status == new_status:
            return

        app_service = ApplicationService(self.db)
        await app_service.update_status(
            account.user_id,
            application.id,
            new_status,
            description=f"Auto-detected from email: {classification.value.replace('_', ' ')}.",
        )
        await self.email_repo.update_fields(email_row.id, status_applied=True)


class EmailQueryService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = EmailRepository(db)
        self.account_repo = EmailAccountRepository(db)
        self.thread_repo = EmailThreadRepository(db)
        self.job_repo = EmailSyncJobRepository(db)

    async def list_emails(self, user_id: str, **filters):
        return await self.repo.search(user_id, **filters)

    async def get_email(self, user_id: str, email_id: str):
        email_row = await self.repo.get_owned(email_id, user_id)
        if not email_row:
            raise EmailNotFoundError(str(email_id))
        if not email_row.is_read:
            await self.repo.update_fields(email_row.id, is_read=True)
            email_row = await self.repo.get_owned(email_id, user_id)
        return email_row

    async def manual_link(self, user_id: str, email_id: str, application_id: str):
        email_row = await self.repo.get_owned(email_id, user_id)
        if not email_row:
            raise EmailNotFoundError(str(email_id))
        app_service = ApplicationService(self.db)
        application = await app_service.get_application(user_id, application_id)
        await self.repo.update_fields(email_row.id, linked_application_id=application.id, match_method="manual", match_confidence=100.0)
        return await self.repo.get_owned(email_id, user_id)

    async def list_sync_jobs(self, user_id: str, account_id: str):
        return await self.job_repo.list_for_account(account_id)


def _map_ai_status_to_classification(ai_status_value: str) -> EmailClassificationEnum:
    """Bridges app.ai_core.models.EmailStatusEnum (owned by the AI analysis
    engine) to this module's EmailClassificationEnum (owned by the ingestion
    layer), since the two enums serve different call sites but describe the
    same underlying concept.
    """
    mapping = {
        "applied": EmailClassificationEnum.APPLICATION_SUBMITTED_CONFIRMATION,
        "under_review": EmailClassificationEnum.UNDER_REVIEW,
        "shortlisted": EmailClassificationEnum.SHORTLISTED,
        "interview_scheduled": EmailClassificationEnum.INTERVIEW_SCHEDULED,
        "assessment_sent": EmailClassificationEnum.ASSESSMENT_REQUEST,
        "offer_received": EmailClassificationEnum.OFFER_RECEIVED,
        "rejected": EmailClassificationEnum.REJECTION,
        "follow_up_required": EmailClassificationEnum.FOLLOW_UP_REQUEST,
        "no_response": EmailClassificationEnum.GENERAL_RECRUITER_MESSAGE,
    }
    return mapping.get(ai_status_value, EmailClassificationEnum.UNKNOWN)
