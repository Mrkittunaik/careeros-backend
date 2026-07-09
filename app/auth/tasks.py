import asyncio
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from app.core.celery_app import celery_app
from app.core.config import settings

logger = logging.getLogger("app.auth.tasks")


def _send_smtp_email(to_email: str, subject: str, html_body: str) -> None:
    if not settings.SMTP_HOST:
        # No SMTP configured (e.g. local dev) — log instead of failing the task.
        logger.info("smtp_not_configured_skipping_send", extra={"to": to_email, "subject": subject})
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.MAIL_FROM_ADDRESS
    msg["To"] = to_email
    msg.set_content("This email requires an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


@celery_app.task(name="app.auth.tasks.send_verification_email", bind=True, max_retries=3)
def send_verification_email(self, to_email: str, full_name: str, token: str) -> dict:
    link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={token}"
    body = (
        f"<p>Hi {full_name},</p>"
        f"<p>Please verify your CareerOS AI account by clicking the link below. "
        f"This link expires in {settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES} minutes.</p>"
        f'<p><a href="{link}">{link}</a></p>'
    )
    try:
        _send_smtp_email(to_email, "Verify your CareerOS AI account", body)
        return {"status": "sent", "to": to_email}
    except Exception as exc:  # noqa: BLE001
        logger.exception("send_verification_email_failed")
        raise self.retry(exc=exc, countdown=30) from exc


@celery_app.task(name="app.auth.tasks.send_password_reset_email", bind=True, max_retries=3)
def send_password_reset_email(self, to_email: str, full_name: str, token: str) -> dict:
    link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={token}"
    body = (
        f"<p>Hi {full_name},</p>"
        f"<p>We received a request to reset your CareerOS AI password. "
        f"This link expires in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes. "
        f"If you didn't request this, you can safely ignore this email.</p>"
        f'<p><a href="{link}">{link}</a></p>'
    )
    try:
        _send_smtp_email(to_email, "Reset your CareerOS AI password", body)
        return {"status": "sent", "to": to_email}
    except Exception as exc:  # noqa: BLE001
        logger.exception("send_password_reset_email_failed")
        raise self.retry(exc=exc, countdown=30) from exc


@celery_app.task(name="app.auth.tasks.purge_expired_sessions", bind=True, max_retries=3)
def purge_expired_sessions(self) -> dict:
    """Celery Beat scheduled task: purges expired sessions nightly."""

    async def _run() -> int:
        from app.auth.repositories import SessionRepository
        from app.core.mongo import get_default_mongo_db

        repo = SessionRepository(get_default_mongo_db())
        return await repo.delete_expired(before=datetime.now(timezone.utc))

    try:
        deleted_count = asyncio.run(_run())
        logger.info("purge_expired_sessions_completed", extra={"deleted": deleted_count})
        return {"deleted": deleted_count}
    except Exception as exc:  # noqa: BLE001
        logger.exception("purge_expired_sessions_failed")
        raise self.retry(exc=exc, countdown=60) from exc


@celery_app.task(name="app.auth.tasks.log_activity_async")
def log_activity_async(action: str, status_value: str, user_id: str | None = None, metadata: dict | None = None) -> dict:
    """Fire-and-forget audit logging, kept off the request hot-path."""

    async def _run() -> None:
        from app.auth.models import AuthActionEnum
        from app.auth.repositories import AuditLogRepository
        from app.core.mongo import get_default_mongo_db

        repo = AuditLogRepository(get_default_mongo_db())
        await repo.log(
            AuthActionEnum(action),
            status_value,
            user_id=user_id,
            metadata=metadata or {},
        )

    asyncio.run(_run())
    return {"status": "logged", "action": action}
