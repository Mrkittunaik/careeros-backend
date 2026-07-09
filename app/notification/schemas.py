import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.notification.constants import MAX_MESSAGE_LENGTH, MAX_TITLE_LENGTH
from app.notification.enums import (
    DeliveryMethodEnum,
    DeliveryStatusEnum,
    NotificationCategoryEnum,
    NotificationPriorityEnum,
    NotificationStatusEnum,
    ReminderStatusEnum,
    ReminderTypeEnum,
    ReportPeriodEnum,
    ScheduledJobStatusEnum,
)


# --- Notifications ---

class NotificationCreateRequest(BaseModel):
    user_id: uuid.UUID
    title: str = Field(max_length=MAX_TITLE_LENGTH)
    message: str = Field(max_length=MAX_MESSAGE_LENGTH)
    category: NotificationCategoryEnum
    priority: NotificationPriorityEnum | None = None
    source_module: str | None = Field(default=None, max_length=64)
    related_application_id: uuid.UUID | None = None
    related_job_id: uuid.UUID | None = None
    action_url: str | None = Field(default=None, max_length=1024)
    metadata: dict = Field(default_factory=dict)
    delivery_methods: list[DeliveryMethodEnum] | None = None


class NotificationDeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    method: DeliveryMethodEnum
    status: DeliveryStatusEnum
    attempt_count: int
    last_error: str | None
    delivered_at: datetime | None


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    message: str
    category: NotificationCategoryEnum
    priority: NotificationPriorityEnum
    status: NotificationStatusEnum
    delivery_method: DeliveryMethodEnum
    source_module: str | None
    related_application_id: uuid.UUID | None
    related_job_id: uuid.UUID | None
    action_url: str | None
    read_at: datetime | None
    dismissed_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    limit: int
    offset: int


class NotificationListQuery(BaseModel):
    category: list[NotificationCategoryEnum] | None = None
    priority: list[NotificationPriorityEnum] | None = None
    unread_only: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class NotificationMarkReadRequest(BaseModel):
    notification_ids: list[uuid.UUID] = Field(min_length=1)


class NotificationDeleteRequest(BaseModel):
    notification_ids: list[uuid.UUID] = Field(min_length=1)


# --- Preferences ---

class NotificationPreferenceUpdateRequest(BaseModel):
    category: NotificationCategoryEnum
    in_app_enabled: bool = True
    push_enabled: bool = True
    email_enabled: bool = True
    websocket_enabled: bool = True


class NotificationPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: NotificationCategoryEnum
    in_app_enabled: bool
    push_enabled: bool
    email_enabled: bool
    websocket_enabled: bool


# --- Reminders ---

class ReminderCreateRequest(BaseModel):
    reminder_type: ReminderTypeEnum
    target_event_at: datetime
    related_application_id: uuid.UUID | None = None
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reminder_type: ReminderTypeEnum
    status: ReminderStatusEnum
    related_application_id: uuid.UUID | None
    target_event_at: datetime
    fire_at: datetime
    lead_minutes: int
    message: str | None
    sent_at: datetime | None


class ReminderListResponse(BaseModel):
    items: list[ReminderResponse]
    total: int


# --- Scheduler ---

class ScheduledJobResponse(BaseModel):
    name: str
    task: str
    schedule: str
    queue: str | None = None


class ScheduledJobRunRequest(BaseModel):
    job_name: str = Field(max_length=128)


class ScheduledJobRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_name: str
    queue: str | None
    status: ScheduledJobStatusEnum
    started_at: datetime | None
    finished_at: datetime | None
    retry_count: int
    error: str | None
    created_at: datetime


class ScheduledJobHistoryResponse(BaseModel):
    items: list[ScheduledJobRunResponse]
    total: int
    limit: int
    offset: int


# --- Reports ---

class ReportRequest(BaseModel):
    period: ReportPeriodEnum = ReportPeriodEnum.DAILY
    start_date: datetime | None = None
    end_date: datetime | None = None


class ReportResponse(BaseModel):
    period: ReportPeriodEnum
    start_date: datetime
    end_date: datetime
    applications_submitted: int
    interviews_scheduled: int
    offers_received: int
    rejections: int
    success_rate: float
    ai_recommendations_generated: int


# --- Health ---

class SystemHealthComponentResponse(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class SystemHealthResponse(BaseModel):
    overall_healthy: bool
    components: list[SystemHealthComponentResponse]
    checked_at: datetime
