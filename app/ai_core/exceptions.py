from app.core.exceptions import AppError, ForbiddenError, NotFoundError, ValidationAppError


class AIEngineError(AppError):
    """Generic AI engine failure. `stage` identifies which pipeline stage
    failed, matching the structured error format required by the master
    prompt: {status, error_code, stage, message, fallback_used}.
    """

    code = "AI_001"
    status_code = 502

    def __init__(self, stage: str, message: str, *, fallback_used: bool = False):
        super().__init__(message, details={"stage": stage, "fallback_used": fallback_used})
        self.stage = stage
        self.fallback_used = fallback_used


class JobProfileNotFoundError(NotFoundError):
    code = "AI_002"

    def __init__(self, job_profile_id: str):
        super().__init__("Job profile not found.", details={"job_profile_id": job_profile_id})


class JobProfileAccessDeniedError(ForbiddenError):
    code = "AI_003"

    def __init__(self):
        super().__init__("You do not have access to this job profile.")


class InvalidToolCallError(ValidationAppError):
    code = "AI_004"

    def __init__(self, tool_name: str, reason: str):
        super().__init__(f"Invalid tool call '{tool_name}': {reason}", details={"tool_name": tool_name})


class PromptTemplateNotFoundError(NotFoundError):
    code = "AI_005"

    def __init__(self, prompt_key: str):
        super().__init__("Prompt template not found.", details={"prompt_key": prompt_key})


class EmailAnalysisFailedError(AIEngineError):
    code = "AI_006"

    def __init__(self, reason: str):
        super().__init__(stage="email_analysis", message=f"Email analysis failed: {reason}")


class CoverLetterGenerationFailedError(AIEngineError):
    code = "AI_007"

    def __init__(self, reason: str):
        super().__init__(stage="cover_letter_generation", message=f"Cover letter generation failed: {reason}")


class ColdEmailGenerationFailedError(AIEngineError):
    code = "AI_008"

    def __init__(self, reason: str):
        super().__init__(stage="cold_email_generation", message=f"Cold email generation failed: {reason}")


class JobIntelligenceFailedError(AIEngineError):
    code = "AI_009"

    def __init__(self, reason: str):
        super().__init__(stage="job_intelligence", message=f"Job description analysis failed: {reason}")


class ResumeMatchingFailedError(AIEngineError):
    code = "AI_010"

    def __init__(self, reason: str):
        super().__init__(stage="job_matching", message=f"Resume-job matching failed: {reason}")


class AllProvidersExhaustedError(AIEngineError):
    code = "AI_011"

    def __init__(self, stage: str, providers_tried: list[str]):
        super().__init__(stage=stage, message="AI provider failed.", fallback_used=len(providers_tried) > 1)
        self.details["providers_tried"] = providers_tried
