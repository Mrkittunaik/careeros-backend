"""Email Communication module Celery tasks — MongoDB version.

Converted from SQLAlchemy/Postgres (old version kept as
tasks.py.postgres.bak). Background tasks run outside FastAPI's request
lifecycle, so there's no authenticated user to resolve a possible
bring-your-own-database connection through — following the precedent set
by app.resume.tasks / app.application.tasks, these always operate against
the shared default Mongo database via `get_default_mongo_db()`, never a
user's own database.
"""

import asyncio
import logging

from celery.schedules import crontab

from app.core.celery_app import celery_app
from app.email_comm.enums import SyncTriggerEnum

logger = logging.getLogger("app.email_comm.tasks")


@celery_app.task(name="app.email_comm.tasks.sync_account", bind=True, max_retries=3, default_retry_delay=60)
def sync_account(self, account_id: str, trigger: str = "manual", historical_days: int | None = None) -> dict:
    """EMAIL_SYNC_QUEUE worker: runs the full ingestion flow (fetch -> filter
    -> parse -> store -> AI classify -> match -> status update) for a single
    connected mailbox. Triggered manually, on a schedule, or by webhook.
    """

    async def _run() -> dict:
        from app.core.mongo import get_default_mongo_db
        from app.email_comm.service import EmailIngestionService

        db = get_default_mongo_db()
        service = EmailIngestionService(db)
        try:
            job_id = await service.sync_account(
                account_id,
                trigger=SyncTriggerEnum(trigger),
                historical_days=historical_days,
            )
            return {"status": "ok", "job_id": str(job_id)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("email_sync_failed", extra={"account_id": account_id, "trigger": trigger})
            return {"status": "failed", "error": str(exc)}

    return asyncio.run(_run())


@celery_app.task(name="app.email_comm.tasks.sync_all_accounts", bind=True, max_retries=1)
def sync_all_accounts(self) -> dict:
    """Scheduled poll fallback for accounts without an active webhook (or
    whose webhook lease has expired), per the spec's Real-Time Email
    Monitoring section ("Polling fallback / Scheduled sync jobs")."""

    async def _run() -> dict:
        from app.core.mongo import get_default_mongo_db
        from app.email_comm.repository import EmailAccountRepository

        db = get_default_mongo_db()
        repo = EmailAccountRepository(db)
        accounts = await repo.list_syncable()
        for account in accounts:
            sync_account.delay(str(account.id), trigger=SyncTriggerEnum.SCHEDULED.value)
        return {"queued": len(accounts)}

    return asyncio.run(_run())


@celery_app.task(name="app.email_comm.tasks.handle_gmail_webhook", bind=True, max_retries=3, default_retry_delay=30)
def handle_gmail_webhook(self, email_address: str, history_id: str) -> dict:
    """NOTIFICATION_QUEUE-adjacent entrypoint for Gmail Pub/Sub push
    notifications: resolves the account by address and triggers a delta
    sync from the given historyId."""

    async def _run() -> dict:
        from app.core.mongo import get_default_mongo_db

        db = get_default_mongo_db()
        # EmailAccountRepository.get_by_address requires a user_id (accounts
        # are scoped per-user), but webhooks only give us the mailbox
        # address, so look it up directly against the collection instead.
        doc = await db["email_accounts"].find_one(
            {"email_address": email_address, "is_deleted": False}
        )
        from app.email_comm.models import EmailAccount

        account = EmailAccount.from_mongo(doc)
        if not account:
            logger.warning("gmail_webhook_unknown_account", extra={"email_address": email_address})
            return {"status": "ignored", "reason": "unknown_account"}

        sync_account.delay(str(account.id), trigger=SyncTriggerEnum.WEBHOOK.value)
        return {"status": "queued", "account_id": str(account.id)}

    return asyncio.run(_run())


@celery_app.task(name="app.email_comm.tasks.handle_outlook_webhook", bind=True, max_retries=3, default_retry_delay=30)
def handle_outlook_webhook(self, subscription_id: str) -> dict:
    """Notification entrypoint for Microsoft Graph change notifications."""

    async def _run() -> dict:
        from app.core.mongo import get_default_mongo_db
        from app.email_comm.models import EmailAccount

        db = get_default_mongo_db()
        doc = await db["email_accounts"].find_one(
            {"webhook_channel_id": subscription_id, "is_deleted": False}
        )
        account = EmailAccount.from_mongo(doc)
        if not account:
            logger.warning("outlook_webhook_unknown_subscription", extra={"subscription_id": subscription_id})
            return {"status": "ignored", "reason": "unknown_subscription"}

        sync_account.delay(str(account.id), trigger=SyncTriggerEnum.WEBHOOK.value)
        return {"status": "queued", "account_id": str(account.id)}

    return asyncio.run(_run())


@celery_app.task(name="app.email_comm.tasks.renew_webhooks", bind=True, max_retries=1)
def renew_webhooks(self) -> dict:
    """Gmail watch requests expire after 7 days and Outlook subscriptions
    after ~3 days max — this periodic task re-registers webhooks that are
    close to expiry so real-time monitoring doesn't silently degrade to
    polling-only."""

    async def _run() -> dict:
        import datetime

        from app.core.mongo import get_default_mongo_db
        from app.core.security import decrypt_secret
        from app.email_comm.enums import EmailAccountStatusEnum, EmailProviderEnum
        from app.email_comm.providers import build_client
        from app.email_comm.repository import EmailAccountRepository

        db = get_default_mongo_db()
        repo = EmailAccountRepository(db)

        soon = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=12)
        renewed = 0
        accounts = await repo.list_syncable()
        for account in accounts:
            if account.provider == EmailProviderEnum.IMAP:
                continue
            if account.webhook_expires_at and account.webhook_expires_at > soon:
                continue
            try:
                access_token = decrypt_secret(account.encrypted_access_token) if account.encrypted_access_token else ""
                refresh_token = decrypt_secret(account.encrypted_refresh_token) if account.encrypted_refresh_token else None
                client = build_client(account, access_token=access_token, refresh_token=refresh_token)
                await client.register_webhook()
                renewed += 1
            except Exception:  # noqa: BLE001
                logger.exception("webhook_renewal_failed", extra={"account_id": str(account.id)})
                await repo.update_fields(account.id, status=EmailAccountStatusEnum.ERROR)
        return {"renewed": renewed}

    return asyncio.run(_run())


# Registered on celery beat here; enabling requires adding these entries to
# app.core.celery_app.celery_app.conf.beat_schedule (kept centralized there
# rather than duplicated per-module):
#   "sync-all-email-accounts": {"task": "app.email_comm.tasks.sync_all_accounts", "schedule": crontab(minute="*/15")},
#   "renew-email-webhooks": {"task": "app.email_comm.tasks.renew_webhooks", "schedule": crontab(hour="*/6")},
