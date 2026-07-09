from app.core.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationAppError


class ResumeNotFoundError(NotFoundError):
    code = "RESUME_001"

    def __init__(self, resume_id: str):
        super().__init__("Resume not found.", details={"resume_id": resume_id})


class ResumeParsingFailedError(AppError):
    code = "RESUME_002"

    def __init__(self, reason: str):
        super().__init__("Resume parsing failed.", details={"reason": reason})


class InvalidFileTypeError(ValidationAppError):
    code = "RESUME_003"

    def __init__(self, filename: str):
        super().__init__(
            "Only PDF and DOCX files are supported.", details={"filename": filename}
        )


class FileTooLargeError(ValidationAppError):
    code = "RESUME_004"

    def __init__(self, max_size_mb: int):
        super().__init__(
            f"File exceeds the maximum allowed size of {max_size_mb}MB.",
            details={"max_size_mb": max_size_mb},
        )


class ResumeAccessDeniedError(ForbiddenError):
    code = "RESUME_005"

    def __init__(self):
        super().__init__("You do not have access to this resume.")


class AIProviderUnavailableError(AppError):
    code = "RESUME_006"
    status_code = 503

    def __init__(self, providers_tried: list[str]):
        super().__init__(
            "All configured AI providers failed to respond.",
            details={"providers_tried": providers_tried},
        )


class ATSScoringFailedError(AppError):
    code = "RESUME_007"

    def __init__(self, reason: str):
        super().__init__("ATS scoring failed.", details={"reason": reason})


class JobMatchingFailedError(AppError):
    code = "RESUME_008"

    def __init__(self, reason: str):
        super().__init__("Resume-job matching failed.", details={"reason": reason})


class NoResumesAvailableError(ConflictError):
    code = "RESUME_009"

    def __init__(self):
        super().__init__("User has no resumes available for selection.")


class EmbeddingGenerationFailedError(AppError):
    code = "RESUME_010"

    def __init__(self, reason: str):
        super().__init__("Failed to generate resume embeddings.", details={"reason": reason})


class InvalidSelectionRuleError(ValidationAppError):
    code = "RESUME_011"

    def __init__(self, reason: str):
        super().__init__(reason)


class DuplicateResumeVersionError(ConflictError):
    code = "RESUME_012"

    def __init__(self):
        super().__init__("A resume version conflict occurred; please retry.")
