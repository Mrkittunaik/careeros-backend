import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.notification.enums import (
    DeliveryMethodEnum,
    DeliveryStatusEnum,
    NotificationCategoryEnum,
    NotificationPriorityEnum,
    NotificationStatusEnum,
    ReminderStatusEnum,
    ReminderTypeEnum,
    ScheduledJobStatusEnum,
)


class Notification(Base):
    """A single notification instance for a user, per the spec's
    NOTIFICATION ENTITY section. `delivery_method` here records the
    *primary* channel for quick filtering; the full fan-out record for
    every channel actually attempted lives in NotificationDelivery.
    """

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[NotificationCategoryEnum] = mapped_column(
        SAEnum(NotificationCategoryEnum, name="notification_category_enum"), nullable=False, index=True
    )
    priority: Mapped[NotificationPriorityEnum] = mapped_column(
        SAEnum(NotificationPriorityEnum, name="notification_priority_enum"),
        default=NotificationPriorityEnum.NORMAL,
        nullable=False,
        index=True,
    )
    status: Mapped[NotificationStatusEnum] = mapped_column(
        SAEnum(NotificationStatusEnum, name="notification_status_enum"),
        default=NotificationStatusEnum.PENDING,
        nullable=False,
        index=True,
    )
    delivery_method: Mapped[DeliveryMethodEnum] = mapped_column(
        SAEnum(DeliveryMethodEnum, name="notification_delivery_method_enum"),
        default=DeliveryMethodEnum.IN_APP,
        nullable=False,
    )

    source_module: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    related_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    related_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    action_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notification_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        back_populates="notification", cascade="all, delete-orphan"
    )


class NotificationDelivery(Base):
    """Per-channel delivery attempt/result for a Notification. One
    Notification can fan out to Dashboard + Push + Email + WebSocket
    simultaneously per the spec's DELIVERY ENGINE section; each channel's
    outcome is tracked independently here for retry/audit purposes.
    """

    __tablename__ = "notification_deliveries"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[DeliveryMethodEnum] = mapped_column(
        SAEnum(DeliveryMethodEnum, name="notification_delivery_channel_enum"), nullable=False, index=True
    )
    status: Mapped[DeliveryStatusEnum] = mapped_column(
        SAEnum(DeliveryStatusEnum, name="notification_delivery_status_enum"),
        default=DeliveryStatusEnum.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notification: Mapped["Notification"] = relationship(back_populates="deliveries")


class NotificationPreference(Base):
    """Per-user, per-category channel opt-in/opt-out. Absence of a row for
    a given category means "use DEFAULT_DELIVERY_METHODS" (see enums.py).
    """

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[NotificationCategoryEnum] = mapped_column(
        SAEnum(NotificationCategoryEnum, name="notification_category_enum"), nullable=False
    )
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    websocket_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Reminder(Base):
    """A scheduled reminder — one row per lead-time fire, so the "24h / 2h /
    30min before an interview" smart-reminder sequence from the spec is
    modeled as three independent, individually cancellable Reminder rows.
    """

    __tablename__ = "reminders"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reminder_type: Mapped[ReminderTypeEnum] = mapped_column(
        SAEnum(ReminderTypeEnum, name="reminder_type_enum"), nullable=False, index=True
    )
    status: Mapped[ReminderStatusEnum] = mapped_column(
        SAEnum(ReminderStatusEnum, name="reminder_status_enum"),
        default=ReminderStatusEnum.SCHEDULED,
        nullable=False,
        index=True,
    )
    related_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    target_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    lead_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduledJobRun(Base):
    """Audit/history row for a single execution of a Celery Beat task, per
    the spec's `/api/v1/scheduler/history` endpoint and AUDIT LOGGING
    section (Job Scheduled/Started/Finished/Failed, Retry Triggered).
    """

    __tablename__ = "scheduled_job_runs"

    job_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    queue: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ScheduledJobStatusEnum] = mapped_column(
        SAEnum(ScheduledJobStatusEnum, name="scheduled_job_status_enum"),
        default=ScheduledJobStatusEnum.PENDING,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AutomationRetry(Base):
    """Retry history for the AUTOMATION RETRY ENGINE — one row per attempt,
    so a browser-crash / API-timeout retry chain is fully auditable.
    """

    __tablename__ = "automation_retries"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    related_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    succeeded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
