import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.notification.enums import (
    DeliveryStatusEnum,
    NotificationCategoryEnum,
    NotificationPriorityEnum,
    NotificationStatusEnum,
    ReminderStatusEnum,
    ScheduledJobStatusEnum,
)
from app.notification.models import (
    AutomationRetry,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    Reminder,
    ScheduledJobRun,
)


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # --- Notification CRUD ---

    async def create(self, **kwargs) -> Notification:
        notification = Notification(**kwargs)
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def get_owned(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            Notification.is_deleted.is_(False),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        categories: list[NotificationCategoryEnum] | None = None,
        priorities: list[NotificationPriorityEnum] | None = None,
        unread_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        conditions = [Notification.user_id == user_id, Notification.is_deleted.is_(False)]
        if categories:
            conditions.append(Notification.category.in_(categories))
        if priorities:
            conditions.append(Notification.priority.in_(priorities))
        if unread_only:
            conditions.append(Notification.read_at.is_(None))

        count_stmt = select(func.count()).select_from(Notification).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Notification)
            .where(and_(*conditions))
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total

    async def count_unread(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_deleted.is_(False),
                Notification.read_at.is_(None),
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def mark_read(self, notification_ids: list[uuid.UUID], user_id: uuid.UUID) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            update(Notification)
            .where(
                Notification.id.in_(notification_ids),
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=now, status=NotificationStatusEnum.READ, updated_at=now)
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def soft_delete(self, notification_ids: list[uuid.UUID], user_id: uuid.UUID) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            update(Notification)
            .where(Notification.id.in_(notification_ids), Notification.user_id == user_id)
            .values(is_deleted=True, deleted_at=now, updated_at=now)
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def update_status(self, notification_id: uuid.UUID, status: NotificationStatusEnum) -> None:
        await self.session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(status=status, updated_at=datetime.now(timezone.utc))
        )

    # --- Deliveries ---

    async def create_delivery(self, notification_id: uuid.UUID, method, **kwargs) -> NotificationDelivery:
        delivery = NotificationDelivery(notification_id=notification_id, method=method, **kwargs)
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def update_delivery(
        self,
        delivery_id: uuid.UUID,
        *,
        status: DeliveryStatusEnum,
        attempt_count: int,
        last_error: str | None = None,
        delivered_at: datetime | None = None,
    ) -> None:
        values = {"status": status, "attempt_count": attempt_count, "updated_at": datetime.now(timezone.utc)}
        if last_error is not None:
            values["last_error"] = last_error
        if delivered_at is not None:
            values["delivered_at"] = delivered_at
        await self.session.execute(
            update(NotificationDelivery).where(NotificationDelivery.id == delivery_id).values(**values)
        )

    # --- Preferences ---

    async def get_preference(
        self, user_id: uuid.UUID, category: NotificationCategoryEnum
    ) -> NotificationPreference | None:
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
            NotificationPreference.is_deleted.is_(False),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def upsert_preference(self, user_id: uuid.UUID, category: NotificationCategoryEnum, **kwargs) -> NotificationPreference:
        existing = await self.get_preference(user_id, category)
        if existing:
            for key, value in kwargs.items():
                setattr(existing, key, value)
            existing.updated_at = datetime.now(timezone.utc)
            await self.session.flush()
            return existing
        pref = NotificationPreference(user_id=user_id, category=category, **kwargs)
        self.session.add(pref)
        await self.session.flush()
        return pref

    async def list_preferences(self, user_id: uuid.UUID) -> list[NotificationPreference]:
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id, NotificationPreference.is_deleted.is_(False)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # --- Reminders ---

    async def create_reminder(self, **kwargs) -> Reminder:
        reminder = Reminder(**kwargs)
        self.session.add(reminder)
        await self.session.flush()
        return reminder

    async def list_reminders_for_user(self, user_id: uuid.UUID) -> list[Reminder]:
        stmt = (
            select(Reminder)
            .where(Reminder.user_id == user_id, Reminder.is_deleted.is_(False))
            .order_by(Reminder.fire_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_due_reminders(self, *, now: datetime, limit: int = 200) -> list[Reminder]:
        stmt = (
            select(Reminder)
            .where(
                Reminder.status == ReminderStatusEnum.SCHEDULED,
                Reminder.fire_at <= now,
                Reminder.is_deleted.is_(False),
            )
            .order_by(Reminder.fire_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_reminder_sent(self, reminder_id: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(Reminder)
            .where(Reminder.id == reminder_id)
            .values(status=ReminderStatusEnum.SENT, sent_at=now, updated_at=now)
        )

    async def cancel_reminders_for_application(self, application_id: uuid.UUID) -> int:
        stmt = (
            update(Reminder)
            .where(
                Reminder.related_application_id == application_id,
                Reminder.status == ReminderStatusEnum.SCHEDULED,
            )
            .values(status=ReminderStatusEnum.CANCELLED, updated_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def get_reminder_owned(self, reminder_id: uuid.UUID, user_id: uuid.UUID) -> Reminder | None:
        stmt = select(Reminder).where(
            Reminder.id == reminder_id, Reminder.user_id == user_id, Reminder.is_deleted.is_(False)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # --- Scheduled job runs ---

    async def create_job_run(self, **kwargs) -> ScheduledJobRun:
        run = ScheduledJobRun(**kwargs)
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish_job_run(
        self, run_id: uuid.UUID, *, status: ScheduledJobStatusEnum, error: str | None = None, result_metadata: dict | None = None
    ) -> None:
        values = {
            "status": status,
            "finished_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        if error is not None:
            values["error"] = error
        if result_metadata is not None:
            values["result_metadata"] = result_metadata
        await self.session.execute(update(ScheduledJobRun).where(ScheduledJobRun.id == run_id).values(**values))

    async def list_job_history(
        self, *, job_name: str | None = None, limit: int = 20, offset: int = 0
    ) -> tuple[list[ScheduledJobRun], int]:
        conditions = [ScheduledJobRun.is_deleted.is_(False)]
        if job_name:
            conditions.append(ScheduledJobRun.job_name == job_name)

        count_stmt = select(func.count()).select_from(ScheduledJobRun).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(ScheduledJobRun)
            .where(and_(*conditions))
            .order_by(ScheduledJobRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total

    # --- Automation retries ---

    async def create_retry_record(self, **kwargs) -> AutomationRetry:
        retry = AutomationRetry(**kwargs)
        self.session.add(retry)
        await self.session.flush()
        return retry

    async def count_recent_attempts(self, task_name: str, related_application_id: uuid.UUID | None) -> int:
        conditions = [AutomationRetry.task_name == task_name]
        if related_application_id:
            conditions.append(AutomationRetry.related_application_id == related_application_id)
        stmt = select(func.count()).select_from(AutomationRetry).where(and_(*conditions))
        return (await self.session.execute(stmt)).scalar_one()
