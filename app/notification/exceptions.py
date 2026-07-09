from app.core.exceptions import AppError, ForbiddenError, NotFoundError, ValidationAppError


class NotificationNotFoundError(NotFoundError):
    code = "NOTIFICATION_001"

    def __init__(self, notification_id: str):
        super().__init__("Notification not found.", details={"notification_id": notification_id})


class NotificationAccessDeniedError(ForbiddenError):
    code = "NOTIFICATION_002"

    def __init__(self):
        super().__init__("You do not have access to this notification.")


class ReminderNotFoundError(NotFoundError):
    code = "NOTIFICATION_003"

    def __init__(self, reminder_id: str):
        super().__init__("Reminder not found.", details={"reminder_id": reminder_id})


class ScheduledJobNotFoundError(NotFoundError):
    code = "NOTIFICATION_004"

    def __init__(self, job_name: str):
        super().__init__("Scheduled job not found.", details={"job_name": job_name})


class DeliveryFailedError(AppError):
    code = "NOTIFICATION_005"

    def __init__(self, method: str, reason: str):
        super().__init__(
            f"Failed to deliver notification via {method}.", details={"method": method, "reason": reason}
        )


class InvalidReportPeriodError(ValidationAppError):
    code = "NOTIFICATION_006"

    def __init__(self, reason: str):
        super().__init__(reason)


class RetryLimitExceededError(ValidationAppError):
    code = "NOTIFICATION_007"

    def __init__(self, max_retries: int):
        super().__init__(
            f"Maximum retry attempts ({max_retries}) exceeded.", details={"max_retries": max_retries}
        )
