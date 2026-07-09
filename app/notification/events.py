"""Wires the Application module's local event bus (app.application.events)
into the Notification system, so status transitions produce notifications
and, where relevant, smart reminders — without app.application needing any
direct dependency on app.notification (it only knows about its own event
bus; this module does the subscribing).

Call `register()` once at process startup (see app/main.py and
app/core/celery_app.py) for both the API process and Celery workers, since
either can be the one to mutate an Application's status.
"""

import logging

from app.application.enums import ApplicationStatusEnum, TimelineEventTypeEnum
from app.application.events import ApplicationEvent
from app.application.events import on as on_application_event
from app.core.database import AsyncSessionLocal
from app.notification.enums import NotificationCategoryEnum, ReminderTypeEnum

logger = logging.getLogger("app.notification.events")

_STATUS_TO_NOTIFICATION: dict[ApplicationStatusEnum, tuple[NotificationCategoryEnum, str]] = {
    ApplicationStatusEnum.SUBMITTED: (NotificationCategoryEnum.APPLICATION, "Application submitted"),
    ApplicationStatusEnum.APPLIED: (NotificationCategoryEnum.APPLICATION, "Application confirmed"),
    ApplicationStatusEnum.ASSESSMENT: (NotificationCategoryEnum.ASSESSMENT, "Assessment requested"),
    ApplicationStatusEnum.INTERVIEW: (NotificationCategoryEnum.INTERVIEW, "Interview scheduled"),
    ApplicationStatusEnum.OFFER: (NotificationCategoryEnum.OFFER, "Offer received"),
    ApplicationStatusEnum.REJECTED: (NotificationCategoryEnum.REJECTION, "Application update"),
}

_registered = False


def register() -> None:
    global _registered
    if _registered:
        return
    _registered = True

    @on_application_event(TimelineEventTypeEnum.STATUS_CHANGED)
    async def _notify_on_status_change(event: ApplicationEvent) -> None:
        mapping = _STATUS_TO_NOTIFICATION.get(event.to_status)
        if not mapping:
            return
        category, title = mapping

        # Deferred import avoids a hard import-time dependency from
        # app.application -> app.notification at module load.
        from app.notification.service import NotificationService

        async with AsyncSessionLocal() as session:
            service = NotificationService(session)
            company = event.payload.get("company_name", "the company")
            role = event.payload.get("role_title", "the role")
            await service.create_notification(
                event.user_id,
                title=title,
                message=f"Your application for {role} at {company} is now '{event.to_status.value}'.",
                category=category,
                source_module="application",
                related_application_id=event.application_id,
                metadata={"from_status": event.from_status.value if event.from_status else None},
            )

            if event.to_status == ApplicationStatusEnum.INTERVIEW and event.payload.get("interview_at"):
                await service.schedule_reminder_sequence(
                    event.user_id,
                    reminder_type=ReminderTypeEnum.INTERVIEW_UPCOMING,
                    target_event_at=event.payload["interview_at"],
                    related_application_id=event.application_id,
                    message=f"Interview for {role} at {company} coming up.",
                )

            await service.flush_dispatches()
            await session.commit()

    logger.info("notification_events_registered")
