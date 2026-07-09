import logging

logger = logging.getLogger("app.auth.mail")


class MailService:
    """Thin abstraction over outbound email. Actual sending is delegated to a
    Celery task (see tasks.py) so request latency never depends on SMTP.
    """

    @staticmethod
    def queue_verification_email(to_email: str, full_name: str, token: str) -> None:
        from app.auth.tasks import send_verification_email

        send_verification_email.delay(to_email, full_name, token)

    @staticmethod
    def queue_password_reset_email(to_email: str, full_name: str, token: str) -> None:
        from app.auth.tasks import send_password_reset_email

        send_password_reset_email.delay(to_email, full_name, token)
