from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "careeros",
    broker=settings.CELERY_BROKER_URL or settings.REDIS_URL,
    backend=settings.CELERY_RESULT_BACKEND or settings.REDIS_URL,
    include=[
        "app.auth.tasks",
        "app.resume.tasks",
        "app.ai_core.tasks",
        "app.application.tasks",
        "app.email_comm.tasks",
        "app.notification.tasks",
        # Register additional module task modules here as they are built:
        # "app.job.tasks",
        # "app.automation.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)

# Dedicated isolated queues per domain, per architecture spec.
celery_app.conf.task_routes = {
    "app.auth.tasks.*": {"queue": "default"},
    "app.ai.tasks.*": {"queue": "ai"},
    "app.ai_core.tasks.*": {"queue": "ai"},
    "app.automation.tasks.*": {"queue": "automation"},
    "app.email_comm.tasks.*": {"queue": "email"},
    "app.resume.tasks.*": {"queue": "resume"},
    "app.job.tasks.*": {"queue": "job"},
    "app.application.tasks.*": {"queue": "application"},
    "app.notification.tasks.*": {"queue": "notification"},
}

celery_app.conf.task_default_queue = "default"

celery_app.conf.beat_schedule = {
    "purge-expired-sessions": {
        "task": "app.auth.tasks.purge_expired_sessions",
        "schedule": crontab(hour=3, minute=0),
    },
    "sync-all-email-accounts": {
        "task": "app.email_comm.tasks.sync_all_accounts",
        "schedule": crontab(minute="*/15"),
    },
    "renew-email-webhooks": {
        "task": "app.email_comm.tasks.renew_webhooks",
        "schedule": crontab(hour="*/6"),
    },
    # --- Part 8: Notification System + Scheduler ---
    "process-due-reminders": {
        "task": "app.notification.tasks.process_due_reminders",
        "schedule": crontab(minute="*/5"),
    },
    "generate-daily-report": {
        "task": "app.notification.tasks.generate_daily_report",
        "schedule": crontab(hour=23, minute=55),
    },
    "cleanup-old-notifications": {
        "task": "app.notification.tasks.cleanup_old_notifications",
        "schedule": crontab(day_of_week=0, hour=4, minute=0),
    },
}
