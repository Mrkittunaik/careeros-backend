import uuid

from fastapi import APIRouter, Depends, Query, status

from app.ai_core.dependencies import get_ai_core_service
from app.ai_core.schemas import (
    AIUsageSummaryResponse,
    ColdEmailRequest,
    ColdEmailResponse,
    CoverLetterRequest,
    CoverLetterResponse,
    EmailAnalysisResponse,
    EmailAnalyzeRequest,
    JobAnalyzeRequest,
    JobProfileResponse,
    MatchRequest,
    RankResumesRequest,
    ResumeMatchResultResponse,
)
from app.ai_core.service import AICoreService
from app.auth.dependencies import get_current_active_user
from app.auth.models import User

router = APIRouter(prefix="/ai", tags=["AI Engine"])


# --- Job Intelligence ---

@router.post("/jobs/analyze", response_model=JobProfileResponse, status_code=status.HTTP_201_CREATED)
async def analyze_job(
    payload: JobAnalyzeRequest,
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> JobProfileResponse:
    profile = await service.analyze_job(current_user.id, payload.job_description, payload.source_job_id)
    return JobProfileResponse.model_validate(profile)


@router.get("/jobs", response_model=list[JobProfileResponse])
async def list_job_profiles(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> list[JobProfileResponse]:
    profiles = await service.list_job_profiles(current_user.id, limit, offset)
    return [JobProfileResponse.model_validate(p) for p in profiles]


@router.get("/jobs/{job_profile_id}", response_model=JobProfileResponse)
async def get_job_profile(
    job_profile_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> JobProfileResponse:
    profile = await service.get_job_profile(current_user.id, job_profile_id)
    return JobProfileResponse.model_validate(profile)


# --- Matching ---

@router.post("/match", response_model=ResumeMatchResultResponse)
async def match_resume_to_job(
    payload: MatchRequest,
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> ResumeMatchResultResponse:
    result = await service.match_single(current_user.id, payload.resume_id, payload.job_profile_id)
    return ResumeMatchResultResponse.model_validate(result)


@router.post("/match/rank", response_model=list[ResumeMatchResultResponse])
async def rank_resumes_for_job(
    payload: RankResumesRequest,
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> list[ResumeMatchResultResponse]:
    results = await service.rank_resumes(current_user.id, payload.job_profile_id, payload.resume_ids)
    return [ResumeMatchResultResponse.model_validate(r) for r in results]


# --- Cover letter ---

@router.post("/cover-letter", response_model=CoverLetterResponse, status_code=status.HTTP_201_CREATED)
async def generate_cover_letter(
    payload: CoverLetterRequest,
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> CoverLetterResponse:
    letter = await service.generate_cover_letter(
        current_user.id,
        payload.resume_id,
        payload.company_name,
        payload.role_title,
        payload.job_description,
        payload.tone,
        payload.job_profile_id,
    )
    return CoverLetterResponse.model_validate(letter)


# --- Cold email ---

@router.post("/cold-email", response_model=ColdEmailResponse, status_code=status.HTTP_201_CREATED)
async def generate_cold_email(
    payload: ColdEmailRequest,
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> ColdEmailResponse:
    email = await service.generate_cold_email(
        current_user.id,
        payload.resume_id,
        payload.role_title,
        payload.company_name,
        payload.recruiter_name,
        payload.recruiter_title,
        payload.job_profile_id,
    )
    return ColdEmailResponse.model_validate(email)


# --- Email analysis ---

@router.post("/emails/analyze", response_model=EmailAnalysisResponse, status_code=status.HTTP_201_CREATED)
async def analyze_email(
    payload: EmailAnalyzeRequest,
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> EmailAnalysisResponse:
    result = await service.analyze_email(current_user.id, payload.email_text, payload.source_email_id)
    return EmailAnalysisResponse.model_validate(result)


# --- Usage analytics ---

@router.get("/usage", response_model=AIUsageSummaryResponse)
async def get_usage_summary(
    current_user: User = Depends(get_current_active_user),
    service: AICoreService = Depends(get_ai_core_service),
) -> AIUsageSummaryResponse:
    summary = await service.usage_summary(current_user.id)
    return AIUsageSummaryResponse(**summary)
