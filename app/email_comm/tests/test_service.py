"""Service-layer tests for app.email_comm, run against an in-memory
mongomock-motor database rather than a live MongoDB — same "fake infra,
real service logic" approach as app.application/app.autoapply's tests,
using a real (mocked) Motor-compatible client since this module's
repositories are actual Motor queries.

EmailIngestionService's full sync_account/_ingest_message flow calls out
to live provider clients (Gmail/Outlook/IMAP) and the AI analysis engine
(app.ai_core, still Postgres-backed and out of scope for this module's
conversion), so those are exercised at the repository level and via
targeted service methods instead of a full end-to-end sync. Everything
that's pure Mongo-backed business logic (account connection/dedup,
disconnect, email querying/filtering, manual linking, sync-job history)
is tested against the real service classes.
"""

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.email_comm.enums import (
    EmailAccountStatusEnum,
    EmailClassificationEnum,
    EmailFolderCategoryEnum,
    EmailProviderEnum,
    SyncJobStatusEnum,
    SyncTriggerEnum,
)
from app.email_comm.exceptions import (
    EmailAccountAccessDeniedError,
    EmailAccountAlreadyConnectedError,
    EmailAccountNotFoundError,
    EmailNotFoundError,
)
from app.email_comm.models import Email, EmailAccount, EmailSyncJob, EmailThread
from app.email_comm.repository import (
    EmailAccountRepository,
    EmailRepository,
    EmailSyncJobRepository,
    EmailThreadRepository,
)
from app.email_comm.service import EmailAccountService, EmailQueryService


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["email_comm_test"]


@pytest.fixture
def account_service(db) -> EmailAccountService:
    return EmailAccountService(db)


@pytest.fixture
def query_service(db) -> EmailQueryService:
    return EmailQueryService(db)


# --- EmailAccountService.connect_imap / dedup / disconnect ---

@pytest.mark.asyncio
async def test_connect_imap_creates_connected_account(account_service: EmailAccountService) -> None:
    account = await account_service.connect_imap(
        "user-1",
        email_address="me@example.com",
        password="hunter2",
        imap_host="imap.example.com",
        imap_port=993,
        imap_use_ssl=True,
    )

    assert account.status == EmailAccountStatusEnum.CONNECTED
    assert account.provider == EmailProviderEnum.IMAP
    assert account.email_address == "me@example.com"
    # Password must never be stored in plaintext.
    assert account.encrypted_imap_password != "hunter2"
    assert account.encrypted_imap_password is not None


@pytest.mark.asyncio
async def test_connect_imap_rejects_duplicate_mailbox_for_same_user(account_service: EmailAccountService) -> None:
    await account_service.connect_imap(
        "user-1", email_address="me@example.com", password="pw1",
        imap_host="imap.example.com", imap_port=993, imap_use_ssl=True,
    )
    with pytest.raises(EmailAccountAlreadyConnectedError):
        await account_service.connect_imap(
            "user-1", email_address="me@example.com", password="pw2",
            imap_host="imap.example.com", imap_port=993, imap_use_ssl=True,
        )


@pytest.mark.asyncio
async def test_connect_imap_allows_same_address_for_different_users(account_service: EmailAccountService) -> None:
    acc1 = await account_service.connect_imap(
        "user-1", email_address="shared@example.com", password="pw1",
        imap_host="imap.example.com", imap_port=993, imap_use_ssl=True,
    )
    acc2 = await account_service.connect_imap(
        "user-2", email_address="shared@example.com", password="pw2",
        imap_host="imap.example.com", imap_port=993, imap_use_ssl=True,
    )
    assert acc1.id != acc2.id


@pytest.mark.asyncio
async def test_list_accounts_returns_only_owned_non_deleted(account_service: EmailAccountService) -> None:
    await account_service.connect_imap(
        "user-1", email_address="a@example.com", password="pw",
        imap_host="h", imap_port=993, imap_use_ssl=True,
    )
    await account_service.connect_imap(
        "user-2", email_address="b@example.com", password="pw",
        imap_host="h", imap_port=993, imap_use_ssl=True,
    )
    accounts = await account_service.list_accounts("user-1")
    assert len(accounts) == 1
    assert accounts[0].email_address == "a@example.com"


@pytest.mark.asyncio
async def test_disconnect_soft_deletes_and_marks_disconnected(account_service: EmailAccountService) -> None:
    account = await account_service.connect_imap(
        "user-1", email_address="a@example.com", password="pw",
        imap_host="h", imap_port=993, imap_use_ssl=True,
    )
    await account_service.disconnect("user-1", account.id)

    accounts = await account_service.list_accounts("user-1")
    assert accounts == []

    raw = await account_service.repo.get_by_id(account.id)
    assert raw is None  # soft-deleted, excluded by is_deleted filter


@pytest.mark.asyncio
async def test_disconnect_unknown_account_raises_not_found(account_service: EmailAccountService) -> None:
    with pytest.raises(EmailAccountNotFoundError):
        await account_service.disconnect("user-1", "does-not-exist")


@pytest.mark.asyncio
async def test_disconnect_another_users_account_raises_access_denied(account_service: EmailAccountService) -> None:
    account = await account_service.connect_imap(
        "user-1", email_address="a@example.com", password="pw",
        imap_host="h", imap_port=993, imap_use_ssl=True,
    )
    with pytest.raises(EmailAccountAccessDeniedError):
        await account_service.disconnect("user-2", account.id)


# --- EmailQueryService ---

@pytest.mark.asyncio
async def test_get_email_marks_unread_email_as_read(db, query_service: EmailQueryService) -> None:
    from datetime import datetime, timezone

    email_repo = EmailRepository(db)
    email = await email_repo.create(
        user_id="user-1",
        account_id="acct-1",
        provider=EmailProviderEnum.GMAIL,
        message_id="msg-1",
        body_hash="hash-1",
        from_email="recruiter@company.com",
        subject="Interview invite",
        received_at=datetime.now(timezone.utc),
        is_read=False,
    )

    fetched = await query_service.get_email("user-1", email.id)
    assert fetched.is_read is True

    refetched = await email_repo.get_owned(email.id, "user-1")
    assert refetched.is_read is True


@pytest.mark.asyncio
async def test_get_email_not_found_raises(query_service: EmailQueryService) -> None:
    with pytest.raises(EmailNotFoundError):
        await query_service.get_email("user-1", "does-not-exist")


@pytest.mark.asyncio
async def test_list_emails_filters_by_job_related_and_paginates(db, query_service: EmailQueryService) -> None:
    from datetime import datetime, timezone

    email_repo = EmailRepository(db)
    for i in range(3):
        await email_repo.create(
            user_id="user-1",
            account_id="acct-1",
            provider=EmailProviderEnum.GMAIL,
            message_id=f"msg-{i}",
            body_hash=f"hash-{i}",
            from_email="recruiter@company.com",
            subject=f"Job related {i}",
            received_at=datetime.now(timezone.utc),
            is_job_related=True,
        )
    await email_repo.create(
        user_id="user-1",
        account_id="acct-1",
        provider=EmailProviderEnum.GMAIL,
        message_id="msg-newsletter",
        body_hash="hash-newsletter",
        from_email="news@example.com",
        subject="Weekly digest",
        received_at=datetime.now(timezone.utc),
        is_job_related=False,
    )

    emails, total = await query_service.list_emails("user-1", is_job_related=True, page=1, page_size=2)
    assert total == 3
    assert len(emails) == 2

    all_emails, all_total = await query_service.list_emails("user-1", page=1, page_size=10)
    assert all_total == 4
    assert len(all_emails) == 4


@pytest.mark.asyncio
async def test_manual_link_sets_linked_application_and_full_confidence(db, query_service: EmailQueryService) -> None:
    from datetime import datetime, timezone

    from app.application.models import Application
    from app.application.enums import ApplicationStatusEnum

    email_repo = EmailRepository(db)
    email = await email_repo.create(
        user_id="user-1",
        account_id="acct-1",
        provider=EmailProviderEnum.GMAIL,
        message_id="msg-1",
        body_hash="hash-1",
        from_email="recruiter@company.com",
        subject="Following up",
        received_at=datetime.now(timezone.utc),
    )

    application = Application(
        user_id="user-1",
        company_name="Acme Corp",
        role_title="Backend Engineer",
        status=ApplicationStatusEnum.SUBMITTED,
    )
    await db["applications"].insert_one(application.to_mongo())

    linked = await query_service.manual_link("user-1", email.id, application.id)
    assert linked.linked_application_id == application.id
    assert linked.match_method == "manual"
    assert linked.match_confidence == 100.0


@pytest.mark.asyncio
async def test_list_sync_jobs_returns_jobs_for_account_ordered_newest_first(db, query_service: EmailQueryService) -> None:
    job_repo = EmailSyncJobRepository(db)
    job1 = await job_repo.create(user_id="user-1", account_id="acct-1", trigger=SyncTriggerEnum.INITIAL_IMPORT)
    await job_repo.mark_completed(job1.id, fetched=10, job_related=3, failed=0)
    job2 = await job_repo.create(user_id="user-1", account_id="acct-1", trigger=SyncTriggerEnum.MANUAL)
    await job_repo.mark_running(job2.id)

    jobs = await query_service.list_sync_jobs("user-1", "acct-1")
    assert len(jobs) == 2
    assert jobs[0].id == job2.id  # newest first
    assert jobs[0].status == SyncJobStatusEnum.RUNNING
    assert jobs[1].status == SyncJobStatusEnum.COMPLETED


# --- Repository-level tests for ingestion-adjacent behavior ---

@pytest.mark.asyncio
async def test_email_repository_duplicate_detection_by_message_id(db) -> None:
    from datetime import datetime, timezone

    repo = EmailRepository(db)
    await repo.create(
        user_id="user-1", account_id="acct-1", provider=EmailProviderEnum.GMAIL,
        message_id="dup-1", body_hash="hash-a", from_email="a@b.com",
        received_at=datetime.now(timezone.utc),
    )
    assert await repo.exists_by_message_id("acct-1", "dup-1") is True
    assert await repo.exists_by_message_id("acct-1", "not-seen") is False


@pytest.mark.asyncio
async def test_email_repository_duplicate_detection_by_body_hash(db) -> None:
    from datetime import datetime, timezone

    repo = EmailRepository(db)
    await repo.create(
        user_id="user-1", account_id="acct-1", provider=EmailProviderEnum.GMAIL,
        message_id="msg-a", body_hash="same-hash", from_email="a@b.com",
        received_at=datetime.now(timezone.utc),
    )
    assert await repo.exists_by_body_hash("acct-1", "same-hash") is True
    assert await repo.exists_by_body_hash("acct-1", "different-hash") is False


@pytest.mark.asyncio
async def test_thread_repository_get_or_create_then_bump(db) -> None:
    from datetime import datetime, timezone

    repo = EmailThreadRepository(db)
    thread = await repo.get_or_create(
        user_id="user-1", account_id="acct-1", thread_id="thread-1", subject="Re: Application"
    )
    assert thread.message_count == 0

    same_thread = await repo.get_or_create(
        user_id="user-1", account_id="acct-1", thread_id="thread-1", subject="Re: Application"
    )
    assert same_thread.id == thread.id  # get_or_create returns the existing row, doesn't duplicate

    now = datetime.now(timezone.utc)
    await repo.bump(thread.id, last_message_at=now, is_recruiter=True)

    updated = await db["email_threads"].find_one({"_id": thread.id})
    assert updated["message_count"] == 1
    assert updated["has_pending_follow_up"] is True
    assert updated["last_sender_was_recruiter"] is True


@pytest.mark.asyncio
async def test_account_repository_list_syncable_excludes_paused_and_error(db) -> None:
    repo = EmailAccountRepository(db)
    connected = await repo.create(
        user_id="user-1", provider=EmailProviderEnum.GMAIL, email_address="a@example.com",
        status=EmailAccountStatusEnum.CONNECTED,
    )
    await repo.create(
        user_id="user-1", provider=EmailProviderEnum.GMAIL, email_address="b@example.com",
        status=EmailAccountStatusEnum.ERROR,
    )
    await repo.create(
        user_id="user-1", provider=EmailProviderEnum.GMAIL, email_address="c@example.com",
        status=EmailAccountStatusEnum.PAUSED,
    )
    syncing = await repo.create(
        user_id="user-1", provider=EmailProviderEnum.GMAIL, email_address="d@example.com",
        status=EmailAccountStatusEnum.SYNCING,
    )

    syncable = await repo.list_syncable()
    syncable_ids = {a.id for a in syncable}
    assert syncable_ids == {connected.id, syncing.id}


@pytest.mark.asyncio
async def test_sync_job_repository_mark_failed_sets_error_message(db) -> None:
    repo = EmailSyncJobRepository(db)
    job = await repo.create(user_id="user-1", account_id="acct-1", trigger=SyncTriggerEnum.SCHEDULED)
    await repo.mark_failed(job.id, error_message="IMAP connection refused")

    doc = await db["email_sync_jobs"].find_one({"_id": job.id})
    assert doc["status"] == SyncJobStatusEnum.FAILED.value
    assert doc["error_message"] == "IMAP connection refused"
