"""Email Communication module repository — MongoDB (Motor) version.

Converted from SQLAlchemy/Postgres (old version kept as
repository.py.postgres.bak). One repository class per collection, same
shape as app.application.repository / app.autoapply.repository: thin
wrappers around Motor queries, no business logic (that lives in
service.py). Method signatures are kept identical to the Postgres version
wherever reasonably possible — the main change is `uuid.UUID` params
becoming `str` (Mongo _id/foreign keys are plain strings, per
app.core.mongo_base), since callers already pass User.id / row.id values
that are strings under the hood.
"""

from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.mongo_base import utcnow
from app.email_comm.enums import EmailAccountStatusEnum, SyncJobStatusEnum
from app.email_comm.models import Email, EmailAccount, EmailSyncJob, EmailThread


class EmailAccountRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["email_accounts"]

    async def get_by_id(self, account_id: str) -> EmailAccount | None:
        doc = await self.col.find_one({"_id": str(account_id), "is_deleted": False})
        return EmailAccount.from_mongo(doc)

    async def get_owned(self, account_id: str, user_id: str) -> EmailAccount | None:
        doc = await self.col.find_one(
            {"_id": str(account_id), "user_id": str(user_id), "is_deleted": False}
        )
        return EmailAccount.from_mongo(doc)

    async def get_by_address(self, user_id: str, email_address: str) -> EmailAccount | None:
        doc = await self.col.find_one(
            {"user_id": str(user_id), "email_address": email_address, "is_deleted": False}
        )
        return EmailAccount.from_mongo(doc)

    async def list_for_user(self, user_id: str) -> list[EmailAccount]:
        cursor = self.col.find({"user_id": str(user_id), "is_deleted": False}).sort("created_at", -1)
        return [EmailAccount.from_mongo(doc) async for doc in cursor]

    async def list_syncable(self) -> list[EmailAccount]:
        """Accounts eligible for scheduled polling — connected/syncing, not paused/error."""
        cursor = self.col.find(
            {
                "is_deleted": False,
                "status": {
                    "$in": [
                        EmailAccountStatusEnum.CONNECTED.value,
                        EmailAccountStatusEnum.SYNCING.value,
                    ]
                },
            }
        )
        return [EmailAccount.from_mongo(doc) async for doc in cursor]

    async def get_by_webhook_channel_id(self, webhook_channel_id: str) -> EmailAccount | None:
        doc = await self.col.find_one(
            {"webhook_channel_id": webhook_channel_id, "is_deleted": False}
        )
        return EmailAccount.from_mongo(doc)

    async def create(self, **kwargs) -> EmailAccount:
        account = EmailAccount(**kwargs)
        await self.col.insert_one(account.to_mongo())
        return account

    async def update_fields(self, account_id: str, **kwargs) -> None:
        kwargs["updated_at"] = utcnow()
        await self.col.update_one({"_id": str(account_id)}, {"$set": kwargs})

    async def soft_delete(self, account_id: str) -> None:
        await self.col.update_one(
            {"_id": str(account_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": utcnow(),
                    "status": EmailAccountStatusEnum.DISCONNECTED.value,
                    "updated_at": utcnow(),
                }
            },
        )


class EmailRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["emails"]

    async def get_by_id(self, email_id: str) -> Email | None:
        doc = await self.col.find_one({"_id": str(email_id), "is_deleted": False})
        return Email.from_mongo(doc)

    async def get_owned(self, email_id: str, user_id: str) -> Email | None:
        doc = await self.col.find_one(
            {"_id": str(email_id), "user_id": str(user_id), "is_deleted": False}
        )
        return Email.from_mongo(doc)

    async def exists_by_message_id(self, account_id: str, message_id: str) -> bool:
        doc = await self.col.find_one(
            {"account_id": str(account_id), "message_id": message_id}, {"_id": 1}
        )
        return doc is not None

    async def exists_by_body_hash(self, account_id: str, body_hash: str) -> bool:
        doc = await self.col.find_one(
            {"account_id": str(account_id), "body_hash": body_hash}, {"_id": 1}
        )
        return doc is not None

    async def create(self, **kwargs) -> Email:
        email = Email(**kwargs)
        await self.col.insert_one(email.to_mongo())
        return email

    async def update_fields(self, email_id: str, **kwargs) -> None:
        kwargs["updated_at"] = utcnow()
        await self.col.update_one({"_id": str(email_id)}, {"$set": kwargs})

    async def search(
        self,
        user_id: str,
        *,
        is_job_related: bool | None = None,
        classification: str | None = None,
        account_id: str | None = None,
        linked_application_id: str | None = None,
        folder_category: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[Email], int]:
        filt: dict = {"user_id": str(user_id), "is_deleted": False}
        if is_job_related is not None:
            filt["is_job_related"] = is_job_related
        if classification is not None:
            classification = classification.value if hasattr(classification, "value") else classification
            filt["ai_classification"] = classification
        if account_id is not None:
            filt["account_id"] = str(account_id)
        if linked_application_id is not None:
            filt["linked_application_id"] = str(linked_application_id)
        if folder_category is not None:
            folder_category = folder_category.value if hasattr(folder_category, "value") else folder_category
            filt["folder_category"] = folder_category
        if search:
            filt["$or"] = [
                {"subject": {"$regex": search, "$options": "i"}},
                {"company_name": {"$regex": search, "$options": "i"}},
                {"job_title": {"$regex": search, "$options": "i"}},
            ]

        total = await self.col.count_documents(filt)
        cursor = (
            self.col.find(filt)
            .sort("received_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        rows = [Email.from_mongo(doc) async for doc in cursor]
        return rows, total

    async def find_candidates_for_matching(self, user_id: str, *, company_name: str | None, job_title: str | None):
        """Fetch this user's applications for fuzzy company/title matching.
        Kept in email_comm.repository (not cross-imported) to avoid a hard
        module coupling with app.application at the data layer — service
        layer resolves actual Application rows via ApplicationRepository.
        """
        raise NotImplementedError  # matching is delegated to EmailApplicationMatcher, which uses ApplicationRepository directly


class EmailThreadRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["email_threads"]

    async def get_or_create(self, *, user_id: str, account_id: str, thread_id: str, subject: str | None) -> EmailThread:
        doc = await self.col.find_one({"account_id": str(account_id), "thread_id": thread_id})
        if doc:
            return EmailThread.from_mongo(doc)
        thread = EmailThread(
            user_id=str(user_id), account_id=str(account_id), thread_id=thread_id, subject=subject
        )
        await self.col.insert_one(thread.to_mongo())
        return thread

    async def bump(self, thread_id_pk: str, *, last_message_at: datetime, is_recruiter: bool) -> None:
        await self.col.update_one(
            {"_id": str(thread_id_pk)},
            {
                "$inc": {"message_count": 1},
                "$set": {
                    "last_message_at": last_message_at,
                    "last_sender_was_recruiter": is_recruiter,
                    "has_pending_follow_up": is_recruiter,
                    "updated_at": utcnow(),
                },
            },
        )

    async def link_application(self, thread_id_pk: str, application_id: str) -> None:
        await self.col.update_one(
            {"_id": str(thread_id_pk)},
            {"$set": {"linked_application_id": str(application_id), "updated_at": utcnow()}},
        )


class EmailSyncJobRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["email_sync_jobs"]

    async def create(self, **kwargs) -> EmailSyncJob:
        job = EmailSyncJob(**kwargs)
        await self.col.insert_one(job.to_mongo())
        return job

    async def mark_running(self, job_id: str) -> None:
        await self.col.update_one(
            {"_id": str(job_id)},
            {
                "$set": {
                    "status": SyncJobStatusEnum.RUNNING.value,
                    "started_at": utcnow(),
                    "updated_at": utcnow(),
                }
            },
        )

    async def mark_completed(self, job_id: str, *, fetched: int, job_related: int, failed: int) -> None:
        await self.col.update_one(
            {"_id": str(job_id)},
            {
                "$set": {
                    "status": SyncJobStatusEnum.COMPLETED.value,
                    "finished_at": utcnow(),
                    "messages_fetched": fetched,
                    "messages_job_related": job_related,
                    "messages_failed": failed,
                    "updated_at": utcnow(),
                }
            },
        )

    async def mark_failed(self, job_id: str, *, error_message: str) -> None:
        await self.col.update_one(
            {"_id": str(job_id)},
            {
                "$set": {
                    "status": SyncJobStatusEnum.FAILED.value,
                    "finished_at": utcnow(),
                    "error_message": error_message,
                    "updated_at": utcnow(),
                }
            },
        )

    async def list_for_account(self, account_id: str, limit: int = 20) -> list[EmailSyncJob]:
        cursor = (
            self.col.find({"account_id": str(account_id)})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [EmailSyncJob.from_mongo(doc) async for doc in cursor]
