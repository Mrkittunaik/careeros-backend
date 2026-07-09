import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.notification.constants import (
    DEFAULT_LIST_LIMIT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_SECONDS,
    MAX_RETRY_BACKOFF_SECONDS,
    RETRYABLE_REASONS,
)
from app.notification.enums import (
    ASSESSMENT_REMINDER_LEAD_MINUTES,
    DEFAULT_DELIVERY_METHODS,
    DEFAULT_PRIORITY_BY_CATEGORY,
    DeliveryMethodEnum,
    DeliveryStatusEnum,
    INTERVIEW_REMINDER_LEAD_MINUTES,
    NotificationCategoryEnum,
    NotificationPriorityEnum,
    NotificationStatusEnum,
    OFFER_EXPIRY_REMINDER_LEAD_MINUTES,
    ReminderTypeEnum,
    ReportPeriodEnum,
    ScheduledJobStatusEnum,
)
from app.notification.exceptions import (
    NotificationAccessDeniedError,
    NotificationNotFoundError,
    ReminderNotFoundError,
    RetryLimitExceededError,
)
from app.notification.models import Notification, Reminder, ScheduledJobRun
from app.notification.repository import NotificationRepository

logger = logging.getLogger("app.notification.service")

_REMINDER_LEAD_TIMES: dict[ReminderTypeEnum, tuple[int, ...]] = {
    ReminderTypeEnum.INTERVIEW_UPCOMING: INTERVIEW_REMINDER_LEAD_MINUTES,
    ReminderTypeEnum.ASSESSMENT_DEADLINE: ASSESSMENT_REMINDER_LEAD_MINUTES,
    ReminderTypeEnum.OFFER_EXPIRY: OFFER_EXPIRY_REMINDER_LEAD_MINUTES,
}


class NotificationService:
    """Coordination-layer service per Part 8: notification creation +
    multi-channel fan-out, smart reminders, scheduled-job bookkeeping,
    automation retry accounting, and lightweight report aggregation.

    Actual channel delivery (push/email/websocket send) is dispatched to
    Celery (`app.notification.tasks.deliver_notification`) rather than
    performed inline here, so a slow provider never blocks the request/
    transaction that created the notification — matching the "must run in
    the background without affecting API performance" system objective.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = NotificationRepository(session)

    # --- Notifications ---

    async def create_notification(
        self,
        user_id: uuid.UUID,
        *,
        title: str,
        message: str,
        category: NotificationCategoryEnum,
        priority: NotificationPriorityEnum | None = None,
        source_module: str | None = None,
        related_application_id: uuid.UUID | None = None,
        related_job_id: uuid.UUID | None = None,
        action_url: str | None = None,
        metadata: dict | None = None,
        delivery_methods: list[DeliveryMethodEnum] | None = None,
    ) -> Notification:
        resolved_priority = priority or DEFAULT_PRIORITY_BY_CATEGORY.get(category, NotificationPriorityEnum.NORMAL)
        methods = await self._resolve_delivery_methods(user_id, category, delivery_methods)

        notification = await self.repo.create(
            user_id=user_id,
            title=title,
            message=message,
            category=category,
            priority=resolved_priority,
            status=NotificationStatusEnum.PENDING,
            delivery_method=methods[0] if methods else DeliveryMethodEnum.IN_APP,
            source_module=source_module,
            related_application_id=related_application_id,
            related_job_id=related_job_id,
            action_url=action_url,
            notification_metadata=metadata or {},
        )

        for method in methods:
            await self.repo.create_delivery(notification.id, method, status=DeliveryStatusEnum.PENDING, attempt_count=0)

        await self.session.flush()

        # Dispatch background delivery after the row (and its delivery
        # rows) are committed, so the Celery worker can always find them.
        from app.notification.tasks import deliver_notification

        notification_id = notification.id
        methods_values = [m.value for m in methods]

        async def _dispatch() -> None:
            deliver_notification.delay(str(notification_id), methods_values)

        self._pending_dispatch = getattr(self, "_pending_dispatch", [])
        self._pending_dispatch.append(_dispatch)

        return notification

    async def flush_dispatches(self) -> None:
        """Call after commit() in the router layer to actually enqueue any
        Celery deliveries queued up by create_notification during this
        unit of work."""
        for dispatch in getattr(self, "_pending_dispatch", []):
            await dispatch()
        self._pending_dispatch = []

    async def _resolve_delivery_methods(
        self,
        user_id: uuid.UUID,
        category: NotificationCategoryEnum,
        override: list[DeliveryMethodEnum] | None,
    ) -> list[DeliveryMethodEnum]:
        if override:
            return override

        defaults = DEFAULT_DELIVERY_METHODS.get(category, frozenset({DeliveryMethodEnum.IN_APP}))
        preference = await self.repo.get_preference(user_id, category)
        if not preference:
            return list(defaults)

        allowed = []
        channel_flags = {
            DeliveryMethodEnum.IN_APP: preference.in_app_enabled,
            DeliveryMethodEnum.PUSH: preference.push_enabled,
            DeliveryMethodEnum.EMAIL: preference.email_enabled,
            DeliveryMethodEnum.WEBSOCKET: preference.websocket_enabled,
        }
        for method in defaults:
            if channel_flags.get(method, True):
                allowed.append(method)
        return allowed or [DeliveryMethodEnum.IN_APP]

    async def list_notifications(
        self,
        user_id: uuid.UUID,
        *,
        categories: list[NotificationCategoryEnum] | None = None,
        priorities: list[NotificationPriorityEnum] | None = None,
        unread_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> tuple[list[Notification], int, int]:
        items, total = await self.repo.list_for_user(
            user_id,
            categories=categories,
            priorities=priorities,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )
        unread_count = await self.repo.count_unread(user_id)
        return items, total, unread_count

    async def get_notification(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification:
        notification = await self.repo.get_owned(notification_id, user_id)
        if not notification:
            raise NotificationNotFoundError(str(notification_id))
        return notification

    async def mark_read(self, notification_ids: list[uuid.UUID], user_id: uuid.UUID) -> int:
        return await self.repo.mark_read(notification_ids, user_id)

    async def delete_notifications(self, notification_ids: list[uuid.UUID], user_id: uuid.UUID) -> int:
        return await self.repo.soft_delete(notification_ids, user_id)

    # --- Preferences ---

    async def set_preference(self, user_id: uuid.UUID, category: NotificationCategoryEnum, **flags):
        return await self.repo.upsert_preference(user_id, category, **flags)

    async def list_preferences(self, user_id: uuid.UUID):
        return await self.repo.list_preferences(user_id)

    # --- Reminders (Smart Reminder System) ---

    async def schedule_reminder_sequence(
        self,
        user_id: uuid.UUID,
        *,
        reminder_type: ReminderTypeEnum,
        target_event_at: datetime,
        related_application_id: uuid.UUID | None = None,
        message: str | None = None,
    ) -> list[Reminder]:
        """Creates one Reminder row per applicable lead time (e.g. 24h/2h/
        30min before an interview). Lead times whose fire_at has already
        passed relative to now are skipped rather than scheduled in the
        past.
        """
        lead_times = _REMINDER_LEAD_TIMES.get(reminder_type, (24 * 60,))
        now = datetime.now(timezone.utc)
        created: list[Reminder] = []
        for lead_minutes in lead_times:
            fire_at = target_event_at - timedelta(minutes=lead_minutes)
            if fire_at <= now:
                continue
            reminder = await self.repo.create_reminder(
                user_id=user_id,
                reminder_type=reminder_type,
                related_application_id=related_application_id,
                target_event_at=target_event_at,
                fire_at=fire_at,
                lead_minutes=lead_minutes,
                message=message,
            )
            created.append(reminder)
        return created

    async def list_reminders(self, user_id: uuid.UUID) -> list[Reminder]:
        return await self.repo.list_reminders_for_user(user_id)

    async def cancel_reminder(self, reminder_id: uuid.UUID, user_id: uuid.UUID) -> None:
        from sqlalchemy import update as _update

        from app.notification.enums import ReminderStatusEnum as _RSE

        reminder = await self.repo.get_reminder_owned(reminder_id, user_id)
        if not reminder:
            raise ReminderNotFoundError(str(reminder_id))
        await self.session.execute(
            _update(Reminder).where(Reminder.id == reminder.id).values(status=_RSE.CANCELLED)
        )

    async def cancel_reminders_for_application(self, application_id: uuid.UUID) -> int:
        return await self.repo.cancel_reminders_for_application(application_id)

    async def process_due_reminders(self, *, now: datetime | None = None) -> int:
        """Called by the scheduler task every few minutes: finds due
        reminders and turns each into a Notification (in-app + push by
        default), per the spec's REMINDER SYSTEM section."""
        now = now or datetime.now(timezone.utc)
        due = await self.repo.list_due_reminders(now=now)
        category_by_type = {
            ReminderTypeEnum.INTERVIEW_UPCOMING: NotificationCategoryEnum.INTERVIEW,
            ReminderTypeEnum.ASSESSMENT_DEADLINE: NotificationCategoryEnum.ASSESSMENT,
            ReminderTypeEnum.OFFER_EXPIRY: NotificationCategoryEnum.OFFER,
            ReminderTypeEnum.RESUME_UPDATE: NotificationCategoryEnum.RESUME,
            ReminderTypeEnum.FOLLOW_UP: NotificationCategoryEnum.APPLICATION,
            ReminderTypeEnum.RECRUITER_REPLY: NotificationCategoryEnum.RECRUITER,
        }
        for reminder in due:
            category = category_by_type.get(reminder.reminder_type, NotificationCategoryEnum.SCHEDULER)
            await self.create_notification(
                reminder.user_id,
                title=self._reminder_title(reminder.reminder_type, reminder.lead_minutes),
                message=reminder.message or self._reminder_title(reminder.reminder_type, reminder.lead_minutes),
                category=category,
                related_application_id=reminder.related_application_id,
                source_module="scheduler",
                metadata={"reminder_id": str(reminder.id), "lead_minutes": reminder.lead_minutes},
            )
            await self.repo.mark_reminder_sent(reminder.id)
        await self.flush_dispatches()
        return len(due)

    @staticmethod
    def _reminder_title(reminder_type: ReminderTypeEnum, lead_minutes: int) -> str:
        if lead_minutes >= 60:
            when = f"{lead_minutes // 60}h"
        else:
            when = f"{lead_minutes}m"
        labels = {
            ReminderTypeEnum.INTERVIEW_UPCOMING: f"Interview in {when}",
            ReminderTypeEnum.ASSESSMENT_DEADLINE: f"Assessment deadline in {when}",
            ReminderTypeEnum.OFFER_EXPIRY: f"Offer expires in {when}",
            ReminderTypeEnum.RESUME_UPDATE: "Time to update your resume",
            ReminderTypeEnum.FOLLOW_UP: "Follow-up reminder",
            ReminderTypeEnum.RECRUITER_REPLY: "Waiting on recruiter reply",
        }
        return labels.get(reminder_type, "Reminder")

    # --- Scheduled job bookkeeping ---

    async def start_job_run(self, job_name: str, *, queue: str | None = None) -> ScheduledJobRun:
        run = await self.repo.create_job_run(
            job_name=job_name,
            queue=queue,
            status=ScheduledJobStatusEnum.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        return run

    async def finish_job_run(
        self, run_id: uuid.UUID, *, success: bool, error: str | None = None, result_metadata: dict | None = None
    ) -> None:
        status = ScheduledJobStatusEnum.SUCCESS if success else ScheduledJobStatusEnum.FAILED
        await self.repo.finish_job_run(run_id, status=status, error=error, result_metadata=result_metadata)

    async def get_job_history(self, *, job_name: str | None = None, limit: int = 20, offset: int = 0):
        return await self.repo.list_job_history(job_name=job_name, limit=limit, offset=offset)

    # --- Automation retry engine ---

    def compute_backoff_seconds(self, attempt_number: int) -> int:
        backoff = DEFAULT_RETRY_BACKOFF_SECONDS * (2 ** max(attempt_number - 1, 0))
        return min(backoff, MAX_RETRY_BACKOFF_SECONDS)

    async def record_retry_attempt(
        self,
        *,
        task_name: str,
        reason: str,
        attempt_number: int,
        max_retries: int = DEFAULT_MAX_RETRIES,
        user_id: uuid.UUID | None = None,
        related_application_id: uuid.UUID | None = None,
        succeeded: bool | None = None,
        error: str | None = None,
    ):
        if reason not in RETRYABLE_REASONS:
            logger.warning("non_retryable_reason", extra={"task_name": task_name, "reason": reason})
        if attempt_number > max_retries:
            raise RetryLimitExceededError(max_retries)

        next_retry_at = None
        if succeeded is not True and attempt_number < max_retries:
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=self.compute_backoff_seconds(attempt_number))

        return await self.repo.create_retry_record(
            user_id=user_id,
            related_application_id=related_application_id,
            task_name=task_name,
            reason=reason,
            attempt_number=attempt_number,
            max_retries=max_retries,
            succeeded=succeeded,
            error=error,
            next_retry_at=next_retry_at,
        )

    # --- Reports ---

    async def generate_report(
        self, user_id: uuid.UUID, *, period: ReportPeriodEnum, start_date: datetime | None, end_date: datetime | None
    ) -> dict:
        """Aggregates application-outcome stats for the given window. Reads
        directly from app.application.models.Application to avoid
        duplicating application state in this module, per the spec's
        REPORT GENERATION section.
        """
        from sqlalchemy import func, select

        from app.application.enums import ApplicationStatusEnum
        from app.application.models import Application

        now = datetime.now(timezone.utc)
        if period == ReportPeriodEnum.DAILY:
            start_date = start_date or (now - timedelta(days=1))
        elif period == ReportPeriodEnum.WEEKLY:
            start_date = start_date or (now - timedelta(days=7))
        elif period == ReportPeriodEnum.MONTHLY:
            start_date = start_date or (now - timedelta(days=30))
        else:
            start_date = start_date or (now - timedelta(days=1))
        end_date = end_date or now

        base_conditions = [
            Application.user_id == user_id,
            Application.is_deleted.is_(False),
            Application.created_at >= start_date,
            Application.created_at <= end_date,
        ]

        async def _count(*extra) -> int:
            stmt = select(func.count()).select_from(Application).where(*base_conditions, *extra)
            return (await self.session.execute(stmt)).scalar_one()

        submitted = await _count(Application.status != ApplicationStatusEnum.DRAFT)
        interviews = await _count(Application.status.in_([ApplicationStatusEnum.INTERVIEW, ApplicationStatusEnum.OFFER, ApplicationStatusEnum.ACCEPTED]))
        offers = await _count(Application.status.in_([ApplicationStatusEnum.OFFER, ApplicationStatusEnum.ACCEPTED]))
        rejections = await _count(Application.status == ApplicationStatusEnum.REJECTED)

        success_rate = round((offers / submitted) * 100, 2) if submitted else 0.0

        return {
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "applications_submitted": submitted,
            "interviews_scheduled": interviews,
            "offers_received": offers,
            "rejections": rejections,
            "success_rate": success_rate,
            "ai_recommendations_generated": 0,
        }

    # --- Health ---

    async def check_system_health(self) -> dict:
        from app.core.database import check_db_connection
        from app.core.redis_client import check_redis_connection

        components = []
        db_ok = await check_db_connection()
        components.append({"name": "database", "healthy": db_ok, "detail": None if db_ok else "unreachable"})

        redis_ok = await check_redis_connection()
        components.append({"name": "redis", "healthy": redis_ok, "detail": None if redis_ok else "unreachable"})

        overall = all(c["healthy"] for c in components)
        return {"overall_healthy": overall, "components": components, "checked_at": datetime.now(timezone.utc)}
