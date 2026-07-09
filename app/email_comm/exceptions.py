from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationAppError


class EmailAccountNotFoundError(NotFoundError):
    code = "EMAIL_001"

    def __init__(self, account_id: str):
        super().__init__("Email account not found.", details={"account_id": account_id})


class EmailAccountAccessDeniedError(ForbiddenError):
    code = "EMAIL_002"

    def __init__(self):
        super().__init__("You do not have access to this email account.")


class EmailAccountAlreadyConnectedError(ConflictError):
    code = "EMAIL_003"

    def __init__(self, email_address: str):
        super().__init__("This mailbox is already connected.", details={"email_address": email_address})


class EmailProviderAuthError(ValidationAppError):
    code = "EMAIL_004"

    def __init__(self, provider: str, reason: str):
        super().__init__(f"Authentication with {provider} failed.", details={"provider": provider, "reason": reason})


class EmailSyncFailedError(AppError):
    code = "EMAIL_005"
    status_code = 502

    def __init__(self, reason: str, stage: str = "sync"):
        super().__init__("Email sync failed.", details={"stage": stage, "reason": reason})


class EmailClassificationFailedError(AppError):
    code = "EMAIL_006"
    status_code = 502

    def __init__(self, reason: str):
        super().__init__("Unable to classify email.", details={"stage": "classification", "reason": reason})


class EmailNotFoundError(NotFoundError):
    code = "EMAIL_007"

    def __init__(self, email_id: str):
        super().__init__("Email not found.", details={"email_id": email_id})


class UnsupportedProviderError(ValidationAppError):
    code = "EMAIL_008"

    def __init__(self, provider: str):
        super().__init__("Unsupported email provider.", details={"provider": provider})


class ImapConnectionError(ValidationAppError):
    code = "EMAIL_009"

    def __init__(self, reason: str):
        super().__init__("Could not connect to the IMAP server.", details={"reason": reason})
