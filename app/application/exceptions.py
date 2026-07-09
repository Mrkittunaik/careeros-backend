from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationAppError


class ApplicationNotFoundError(NotFoundError):
    code = "APPLICATION_001"

    def __init__(self, application_id: str):
        super().__init__("Application not found.", details={"application_id": application_id})


class ApplicationAccessDeniedError(ForbiddenError):
    code = "APPLICATION_002"

    def __init__(self):
        super().__init__("You do not have access to this application.")


class InvalidStatusTransitionError(ConflictError):
    code = "APPLICATION_003"

    def __init__(self, from_status: str, to_status: str):
        super().__init__(
            f"Cannot transition application from '{from_status}' to '{to_status}'.",
            details={"from_status": from_status, "to_status": to_status},
        )


class ResumeNotAvailableForApplicationError(ValidationAppError):
    code = "APPLICATION_004"

    def __init__(self, resume_id: str):
        super().__init__(
            "The specified resume could not be found or is not owned by you.",
            details={"resume_id": resume_id},
        )


class AttachmentLimitExceededError(ValidationAppError):
    code = "APPLICATION_005"

    def __init__(self, max_attachments: int):
        super().__init__(
            f"An application may have at most {max_attachments} attachments.",
            details={"max_attachments": max_attachments},
        )


class AttachmentNotFoundError(NotFoundError):
    code = "APPLICATION_006"

    def __init__(self, attachment_id: str):
        super().__init__("Attachment not found.", details={"attachment_id": attachment_id})


class AnswerGenerationFailedError(AppError):
    code = "APPLICATION_007"

    def __init__(self, reason: str):
        super().__init__("Failed to generate an AI answer.", details={"reason": reason})


class AnswerNotFoundError(NotFoundError):
    code = "APPLICATION_008"

    def __init__(self, answer_id: str):
        super().__init__("Answer not found.", details={"answer_id": answer_id})


class CoverLetterGenerationFailedError(AppError):
    code = "APPLICATION_009"

    def __init__(self, reason: str):
        super().__init__("Failed to generate a cover letter for this application.", details={"reason": reason})


class PackageBuildFailedError(AppError):
    code = "APPLICATION_010"

    def __init__(self, reason: str):
        super().__init__("Failed to build the application package.", details={"reason": reason})


class InvalidApplicationDataError(ValidationAppError):
    code = "APPLICATION_011"

    def __init__(self, reason: str):
        super().__init__(reason)
