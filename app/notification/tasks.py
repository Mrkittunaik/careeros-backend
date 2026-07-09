import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.notification.enums import DeliveryMethodEnum, DeliveryStatusEnum, NotificationStatusEnum

logger = logging.getLogger("app.notification.tasks")

# Celery workers import this module (via celery_app's `include=[...]`) but
# never run app.main:create_app(), so the application-event -> notification
# bridge needs registering here too — e.g. when app.application.tasks or
# app.email_comm.tasks change an Application's status from a worker
# process, not just from the API process.
from app.notification.events import register as _register_notification_events  # noqa: E402

_register_notification_events()


# --- Delivery engine ---

@celery_app.task(name="app.notification.tasks.deliver_notification", bind=True, max_retries=3, default_retry_delay=30)
def deliver_notification(self, notification_id: str, methods: list[str]) -> dict:
    """NOTIFICATION_QUEUE worker: fans a single Notification out across
    every requested channel. Each channel is attempted independently so a
    failure on one (e.g. email provider down) never blocks the others
    (e.g. in-app / websocket), per the spec's DELIVERY ENGINE section.
    """

    async def _run() -> dict:
        from sqlalchemy import select

        from app.notification.models import Notification, NotificationDelivery
        from app.notification.repository import NotificationRepository

        async with AsyncSessionLocal() as session:
            repo = NotificationRepository(session)
            result = await session.execute(select(Notification).where(Notification.id == uuid.UUID(notification_id)))
            notification = result.scalar_one_or_none()
            if not notification:
                logger.warning("notification_not_found_for_delivery", extra={"notification_id": notification_id})
                return {"status": "skipped", "reason": "not_found"}

            deliveries_result = await session.execute(
                select(NotificationDelivery).where(NotificationDelivery.notification_id == notification.id)
            )
            deliveries = {d.method.value: d for d in deliveries_result.scalars().all()}

            results = {}
            any_success = False
            for method in methods:
                delivery = deliveries.get(method)
                if not delivery:
                    continue
                ok, error = await _send_via_channel(DeliveryMethodEnum(method), notification)
                attempt = delivery.attempt_count + 1
                await repo.update_delivery(
                    delivery.id,
                    status=DeliveryStatusEnum.DELIVERED if ok else DeliveryStatusEnum.FAILED,
                    attempt_count=attempt,
                    last_error=None if ok else error,
                    delivered_at=datetime.now(timezone.utc) if ok else None,
                )
                results[method] = "delivered" if ok else "failed"
                any_success = any_success or ok

            await repo.update_status(
                notification.id, NotificationStatusEnum.DELIVERED if any_success else NotificationStatusEnum.FAILED
            )
            await session.commit()
            return {"status": "ok", "results": results}

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        logger.exception("notification_delivery_failed", extra={"notification_id": notification_id})
        raise self.retry(exc=exc)


async def _send_via_channel(method: DeliveryMethodEnum, notification) -> tuple[bool, str | None]:
    """Per-channel send implementation. IN_APP and WEBSOCKET are always
    considered delivered once the row exists / the pub/sub message is
    published (the frontend reads/subscribes directly); PUSH, EMAIL, SMS,
    WHATSAPP, DESKTOP require an external provider integration that is
    intentionally left as a clearly-marked extension point so wiring in a
    real provider later requires touching only this function.
    """
    try:
        if method == DeliveryMethodEnum.IN_APP:
            return True, None
        if method == DeliveryMethodEnum.WEBSOCKET:
            await _publish_websocket_event(notification)
            return True, None
        if method == DeliveryMethodEnum.EMAIL:
            # TODO: wire to app.auth.mail's SMTP sender for a templated
            # notification email once notification email templates exist.
            logger.info("notification_email_channel_not_configured", extra={"notification_id": str(notification.id)})
            return False, "email_channel_not_configured"
        if method == DeliveryMethodEnum.PUSH:
            logger.info("notification_push_channel_not_configured", extra={"notification_id": str(notification.id)})
            return False, "push_channel_not_configured"
        if method == DeliveryMethodEnum.DESKTOP:
            logger.info("notification_desktop_channel_not_configured", extra={"notification_id": str(notification.id)})
            return False, "desktop_channel_not_configured"
        # SMS / WHATSAPP explicitly marked "future" in the spec.
        return False, f"{method.value}_not_implemented"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


async def _publish_websocket_event(notification) -> None:
    from app.core.redis_client import get_redis
    from app.notification.constants import WEBSOCKET_NOTIFICATION_CHANNEL_PREFIX

    redis = get_redis()
    channel = f"{WEBSOCKET_NOTIFICATION_CHANNEL_PREFIX}{notification.user_id}"
    import json

    await redis.publish(
        channel,
        json.dumps(
            {
                "id": str(notification.id),
                "title": notification.title,
                "message": notification.message,
                "category": notification.category.value,
                "priority": notification.priority.value,
                "created_at": notification.created_at.isoformat() if notification.created_at else None,
            }
        ),
    )


# --- Scheduler-driven background intelligence ---

@celery_app.task(name="app.notification.tasks.process_due_reminders", bind=True, max_retries=1)
def process_due_reminders(self) -> dict:
    """Every-5-minutes task: turns any Reminder rows whose fire_at has
    passed into delivered Notifications (Smart Reminder System)."""

    async def _run() -> dict:
        from app.notification.service import NotificationService

        async with AsyncSessionLocal() as session:
            service = NotificationService(session)
            count = await service.process_due_reminders()
            await session.commit()
            return {"processed": count}

    return asyncio.run(_run())


@celery_app.task(name="app.notification.tasks.generate_daily_report", bind=True, max_retries=1)
def generate_daily_report(self) -> dict:
    """Daily scheduled task per DEFAULT SCHEDULED TASKS: generates and
    stores/notifies a per-user daily analytics summary. Iterates active
    users and fires a LOW-priority "Daily Analytics" notification per the
    spec's worked NOTIFICATION PRIORITY example.
    """

    async def _run() -> dict:
        from sqlalchemy import select

        from app.auth.models import User
        from app.notification.enums import NotificationCategoryEnum, NotificationPriorityEnum
        from app.notification.enums import ReportPeriodEnum
        from app.notification.service import NotificationService

        async with AsyncSessionLocal() as session:
            service = NotificationService(session)
            users_result = await session.execute(select(User).where(User.is_deleted.is_(False)))
            users = users_result.scalars().all()
            generated = 0
            for user in users:
                report = await service.generate_report(
                    user.id, period=ReportPeriodEnum.DAILY, start_date=None, end_date=None
                )
                if report["applications_submitted"] == 0:
                    continue
                await service.create_notification(
                    user.id,
                    title="Your daily activity summary",
                    message=(
                        f"{report['applications_submitted']} applications submitted, "
                        f"{report['interviews_scheduled']} interviews, {report['offers_received']} offers today."
                    ),
                    category=NotificationCategoryEnum.SYSTEM,
                    priority=NotificationPriorityEnum.LOW,
                    source_module="scheduler",
                )
                generated += 1
            await service.flush_dispatches()
            await session.commit()
            return {"reports_generated": generated}

    return asyncio.run(_run())


@celery_app.task(name="app.notification.tasks.cleanup_old_notifications", bind=True, max_retries=1)
def cleanup_old_notifications(self, days: int = 90) -> dict:
    """Weekly housekeeping: soft-deletes read notifications older than N
    days so the notifications table doesn't grow unbounded."""

    async def _run() -> dict:
        from datetime import timedelta

        from sqlalchemy import update

        from app.notification.models import Notification

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                update(Notification)
                .where(
                    Notification.read_at.is_not(None),
                    Notification.created_at < cutoff,
                    Notification.is_deleted.is_(False),
                )
                .values(is_deleted=True, deleted_at=datetime.now(timezone.utc))
            )
            await session.commit()
            return {"cleaned": result.rowcount or 0}

    return asyncio.run(_run())


@celery_app.task(name="app.notification.tasks.record_scheduled_job_run", bind=True, max_retries=1)
def record_scheduled_job_run(self, job_name: str, success: bool, error: str | None = None) -> dict:
    """Helper task other modules' scheduled tasks can call (or wrap with)
    to log a ScheduledJobRun row for the /api/v1/scheduler/history
    endpoint, without every module needing to import notification.service
    directly."""

    async def _run() -> dict:
        from app.notification.enums import ScheduledJobStatusEnum
        from app.notification.repository import NotificationRepository

        async with AsyncSessionLocal() as session:
            repo = NotificationRepository(session)
            run = await repo.create_job_run(
                job_name=job_name,
                status=ScheduledJobStatusEnum.SUCCESS if success else ScheduledJobStatusEnum.FAILED,
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                error=error,
            )
            await session.commit()
            return {"run_id": str(run.id)}

    return asyncio.run(_run())


# Beat schedule additions (registered centrally in app.core.celery_app):
#   "process-due-reminders":  {"task": "app.notification.tasks.process_due_reminders", "schedule": crontab(minute="*/5")},
#   "generate-daily-report":  {"task": "app.notification.tasks.generate_daily_report", "schedule": crontab(hour=23, minute=55)},
#   "cleanup-old-notifications": {"task": "app.notification.tasks.cleanup_old_notifications", "schedule": crontab(day_of_week=0, hour=4)},
