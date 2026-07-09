"""Lightweight in-process event system for the Application module.

No project-wide event bus exists yet (Parts 1-4 are request/response +
Celery only), so this introduces a minimal pub/sub hook local to this
module — deliberately small so it's trivial to swap for a shared
app.core.events bus later without changing call sites in service.py.

Handlers registered here run synchronously, in-process, best-effort: a
handler exception is logged and swallowed so a listener bug can never
break the primary application-mutation transaction. Anything that must be
reliable (e.g. sending a notification) should go through a Celery task
instead of a handler here.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.application.enums import ApplicationStatusEnum, TimelineEventTypeEnum

logger = logging.getLogger("app.application.events")


@dataclass
class ApplicationEvent:
    event_type: TimelineEventTypeEnum
    application_id: str
    user_id: str
    from_status: ApplicationStatusEnum | None = None
    to_status: ApplicationStatusEnum | None = None
    payload: dict = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


EventHandler = Callable[[ApplicationEvent], Awaitable[None]]

_handlers: dict[TimelineEventTypeEnum, list[EventHandler]] = {}


def on(event_type: TimelineEventTypeEnum):
    """Decorator to register a handler for a specific event type."""

    def _register(handler: EventHandler) -> EventHandler:
        _handlers.setdefault(event_type, []).append(handler)
        return handler

    return _register


async def emit(event: ApplicationEvent) -> None:
    for handler in _handlers.get(event.event_type, []):
        try:
            await handler(event)
        except Exception:  # noqa: BLE001
            logger.exception(
                "application_event_handler_failed",
                extra={"event_type": event.event_type.value, "application_id": str(event.application_id)},
            )


@on(TimelineEventTypeEnum.STATUS_CHANGED)
async def _log_status_change(event: ApplicationEvent) -> None:
    logger.info(
        "application_status_changed",
        extra={
            "application_id": str(event.application_id),
            "user_id": str(event.user_id),
            "from_status": event.from_status.value if event.from_status else None,
            "to_status": event.to_status.value if event.to_status else None,
        },
    )


@on(TimelineEventTypeEnum.STATUS_CHANGED)
async def _queue_reminder_side_effects(event: ApplicationEvent) -> None:
    """Placeholder hook where a future notification/reminder Celery task
    would be dispatched on reaching interview/offer/rejected states. Kept
    as a no-op log line for now since notification infrastructure is
    outside Part 5A's scope.
    """
    if event.to_status in {
        ApplicationStatusEnum.INTERVIEW,
        ApplicationStatusEnum.OFFER,
        ApplicationStatusEnum.REJECTED,
    }:
        logger.info(
            "application_status_notable_transition",
            extra={"application_id": str(event.application_id), "to_status": event.to_status.value},
        )
