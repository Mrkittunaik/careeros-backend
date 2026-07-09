from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.dependencies import get_current_active_user
from app.auth.models import User
from app.integrations.dependencies import get_mongo_db_for_user
from app.notification.dependencies import get_notification_service
from app.notification.enums import NotificationCategoryEnum, NotificationPriorityEnum, ReportPeriodEnum
from app.notification.exceptions import ReminderNotFoundError
from app.notification.schemas import (
    NotificationDeleteRequest,
    NotificationListResponse,
    NotificationMarkReadRequest,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateRequest,
    NotificationResponse,
    ReminderCreateRequest,
    ReminderListResponse,
    ReminderResponse,
    ReportRequest,
    ReportResponse,
    ScheduledJobHistoryResponse,
    ScheduledJobRunResponse,
    SystemHealthResponse,
)
from app.notification.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])
scheduler_router = APIRouter(prefix="/scheduler", tags=["Scheduler"])
reports_router = APIRouter(prefix="/reports", tags=["Reports"])


# --- Notifications ---

@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    category: list[NotificationCategoryEnum] | None = Query(default=None),
    priority: list[NotificationPriorityEnum] | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationListResponse:
    items, total, unread_count = await service.list_notifications(
        current_user.id,
        categories=category,
        priorities=priority,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
        unread_count=unread_count,
        limit=limit,
        offset=offset,
    )


@router.post("/read", response_model=dict)
async def mark_notifications_read(
    payload: NotificationMarkReadRequest,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> dict:
    updated = await service.mark_read(payload.notification_ids, current_user.id)
    return {"updated": updated}


@router.post("/delete", response_model=dict)
async def delete_notifications(
    payload: NotificationDeleteRequest,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> dict:
    deleted = await service.delete_notifications(payload.notification_ids, current_user.id)
    return {"deleted": deleted}


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: str,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    import uuid

    notification = await service.get_notification(uuid.UUID(notification_id), current_user.id)
    return NotificationResponse.model_validate(notification)


# --- Preferences ---

@router.get("/preferences/list", response_model=list[NotificationPreferenceResponse])
async def list_preferences(
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> list[NotificationPreferenceResponse]:
    prefs = await service.list_preferences(current_user.id)
    return [NotificationPreferenceResponse.model_validate(p) for p in prefs]


@router.put("/preferences", response_model=NotificationPreferenceResponse)
async def update_preference(
    payload: NotificationPreferenceUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationPreferenceResponse:
    pref = await service.set_preference(
        current_user.id,
        payload.category,
        in_app_enabled=payload.in_app_enabled,
        push_enabled=payload.push_enabled,
        email_enabled=payload.email_enabled,
        websocket_enabled=payload.websocket_enabled,
    )
    return NotificationPreferenceResponse.model_validate(pref)


# --- Reminders ---

@router.get("/reminders/list", response_model=ReminderListResponse)
async def list_reminders(
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> ReminderListResponse:
    reminders = await service.list_reminders(current_user.id)
    return ReminderListResponse(items=[ReminderResponse.model_validate(r) for r in reminders], total=len(reminders))


@router.post("/reminders", response_model=ReminderListResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    payload: ReminderCreateRequest,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> ReminderListResponse:
    reminders = await service.schedule_reminder_sequence(
        current_user.id,
        reminder_type=payload.reminder_type,
        target_event_at=payload.target_event_at,
        related_application_id=payload.related_application_id,
        message=payload.message,
    )
    return ReminderListResponse(items=[ReminderResponse.model_validate(r) for r in reminders], total=len(reminders))


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reminder(
    reminder_id: str,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> None:
    import uuid

    try:
        await service.cancel_reminder(uuid.UUID(reminder_id), current_user.id)
    except ReminderNotFoundError:
        raise


# --- Scheduler ---

@scheduler_router.get("/jobs", response_model=list[dict])
async def list_scheduled_jobs(current_user: User = Depends(get_current_active_user)) -> list[dict]:
    from app.core.celery_app import celery_app

    jobs = []
    for name, entry in celery_app.conf.beat_schedule.items():
        jobs.append({"name": name, "task": entry["task"], "schedule": str(entry["schedule"])})
    return jobs


@scheduler_router.get("/history", response_model=ScheduledJobHistoryResponse)
async def get_scheduler_history(
    job_name: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> ScheduledJobHistoryResponse:
    items, total = await service.get_job_history(job_name=job_name, limit=limit, offset=offset)
    return ScheduledJobHistoryResponse(
        items=[ScheduledJobRunResponse.model_validate(i) for i in items], total=total, limit=limit, offset=offset
    )


@scheduler_router.post("/run", response_model=dict)
async def run_scheduled_job(
    job_name: str,
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Manually trigger a registered Celery Beat task by name (admin/debug
    utility) — dispatches via .delay() using the task registry rather than
    a hardcoded if/else chain."""
    from app.core.celery_app import celery_app

    task = celery_app.tasks.get(job_name)
    if not task:
        from app.notification.exceptions import ScheduledJobNotFoundError

        raise ScheduledJobNotFoundError(job_name)
    async_result = task.delay()
    return {"task_id": async_result.id, "status": "queued"}


# --- Reports ---

@reports_router.post("/generate", response_model=ReportResponse)
async def generate_report(
    payload: ReportRequest,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> ReportResponse:
    report = await service.generate_report(
        current_user.id, period=payload.period, start_date=payload.start_date, end_date=payload.end_date
    )
    return ReportResponse(**report)


@reports_router.get("/daily", response_model=ReportResponse)
async def get_daily_report(
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> ReportResponse:
    report = await service.generate_report(current_user.id, period=ReportPeriodEnum.DAILY, start_date=None, end_date=None)
    return ReportResponse(**report)


@reports_router.get("/weekly", response_model=ReportResponse)
async def get_weekly_report(
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> ReportResponse:
    report = await service.generate_report(current_user.id, period=ReportPeriodEnum.WEEKLY, start_date=None, end_date=None)
    return ReportResponse(**report)


@reports_router.get("/monthly", response_model=ReportResponse)
async def get_monthly_report(
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
) -> ReportResponse:
    report = await service.generate_report(current_user.id, period=ReportPeriodEnum.MONTHLY, start_date=None, end_date=None)
    return ReportResponse(**report)


# --- Activity log (MongoDB) ---
# Demonstrates the shared-default / bring-your-own-database pattern: free
# users write into the shared cluster, paid users who connected their own
# MongoDB (see app.integrations) get their data isolated in their own DB.
# Every call here also counts against the caller's API quota.

@router.post("/activity-log", status_code=status.HTTP_201_CREATED)
async def log_activity(
    action: str,
    metadata: dict | None = None,
    current_user: User = Depends(get_current_active_user),
    mongo_db: AsyncIOMotorDatabase = Depends(get_mongo_db_for_user),
) -> dict:
    doc = {
        "user_id": str(current_user.id),
        "action": action,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc),
    }
    result = await mongo_db["notification_activity_log"].insert_one(doc)
    return {"id": str(result.inserted_id), "action": action}


@router.get("/activity-log")
async def list_activity_log(
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_active_user),
    mongo_db: AsyncIOMotorDatabase = Depends(get_mongo_db_for_user),
) -> list[dict]:
    cursor = (
        mongo_db["notification_activity_log"]
        .find({"user_id": str(current_user.id)})
        .sort("created_at", -1)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    for doc in docs:
        doc["id"] = str(doc.pop("_id"))
    return docs
