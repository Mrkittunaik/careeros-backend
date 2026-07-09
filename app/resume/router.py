"""Resume module router — MongoDB version.

Converted from SQLAlchemy/Postgres (old version kept as
router.py.postgres.bak). Endpoint paths, request/response schemas, and
status codes are all unchanged. The only change is path-parameter typing:
`resume_id`/`rule_id` are now plain `str` instead of `uuid.UUID`, since
Mongo ids are strings end-to-end (same convention as app.application and
app.autoapply) — FastAPI still validates/serializes these fine as strings
in the URL and response bodies.
"""

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.auth.dependencies import get_current_active_user
from app.auth.models import User
from app.resume.dependencies import get_resume_service
from app.resume.exceptions import InvalidFileTypeError
from app.resume.models import AIProviderEnum, ResumeStatusEnum
from app.resume.schemas import (
    AIProviderKeyResponse,
    AIProviderKeySetRequest,
    ATSScoreRequest,
    ATSScoreResponse,
    JobMatchRequest,
    JobMatchResponse,
    ResumeListResponse,
    ResumeOptimizeRequest,
    ResumeOptimizeResponse,
    ResumeParsedDetailResponse,
    ResumeResponse,
    ResumeSearchRequest,
    ResumeSearchResult,
    ResumeSelectionRequest,
    ResumeSelectionResponse,
    ResumeSelectionRuleCreateRequest,
    ResumeSelectionRuleResponse,
    ResumeUpdateRequest,
)
from app.resume.services import ResumeService

router = APIRouter(prefix="/resumes", tags=["Resume Intelligence"])


@router.post("/upload", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    title: str | None = None,
    tags: str | None = Query(default=None, description="Comma-separated tags"),
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeResponse:
    if not file.filename:
        raise InvalidFileTypeError("unknown")
    file_bytes = await file.read()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    resume = await service.upload_resume(current_user.id, file.filename, file_bytes, title, tag_list)
    return ResumeResponse.model_validate(resume)


@router.get("/list", response_model=ResumeListResponse)
async def list_resumes(
    tags: str | None = Query(default=None, description="Comma-separated tags to filter by"),
    status_filter: ResumeStatusEnum | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeListResponse:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    resumes, total = await service.list_resumes(
        current_user.id, tags=tag_list, status=status_filter, limit=limit, offset=offset
    )
    return ResumeListResponse(
        items=[ResumeResponse.model_validate(r) for r in resumes], total=total, limit=limit, offset=offset
    )


@router.get("/rules", response_model=list[ResumeSelectionRuleResponse])
async def list_selection_rules(
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> list[ResumeSelectionRuleResponse]:
    rules = await service.list_selection_rules(current_user.id)
    return [ResumeSelectionRuleResponse.model_validate(r) for r in rules]


@router.post("/rules", response_model=ResumeSelectionRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_selection_rule(
    payload: ResumeSelectionRuleCreateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeSelectionRuleResponse:
    rule = await service.create_selection_rule(
        current_user.id, payload.job_role_pattern, payload.resume_id, payload.priority
    )
    return ResumeSelectionRuleResponse.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_selection_rule(
    rule_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> None:
    await service.delete_selection_rule(current_user.id, rule_id)


@router.post("/select-for-job", response_model=ResumeSelectionResponse)
async def select_for_job(
    payload: ResumeSelectionRequest,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeSelectionResponse:
    result = await service.select_resume_for_job(current_user.id, payload.job_role_title, payload.job_description)
    return ResumeSelectionResponse(**result)


@router.post("/search", response_model=list[ResumeSearchResult])
async def search_resumes(
    payload: ResumeSearchRequest,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> list[ResumeSearchResult]:
    results = await service.search_resumes(
        current_user.id,
        query=payload.query,
        skill=payload.skill,
        job_role=payload.job_role,
        min_ats_score=payload.min_ats_score,
        semantic=payload.semantic,
        limit=payload.limit,
    )
    return [ResumeSearchResult(**r) for r in results]


# --- BYOK AI provider key management ---

@router.get("/ai-keys", response_model=list[AIProviderKeyResponse])
async def list_ai_provider_keys(
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> list[AIProviderKeyResponse]:
    keys = await service.list_ai_provider_keys(current_user.id)
    return [AIProviderKeyResponse.model_validate(k) for k in keys]


@router.put("/ai-keys", response_model=AIProviderKeyResponse)
async def set_ai_provider_key(
    payload: AIProviderKeySetRequest,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> AIProviderKeyResponse:
    key_row = await service.set_ai_provider_key(current_user.id, payload.provider, payload.api_key)
    return AIProviderKeyResponse.model_validate(key_row)


@router.delete("/ai-keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_provider_key(
    provider: AIProviderEnum,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> None:
    await service.delete_ai_provider_key(current_user.id, provider)


# --- Per-resume operations (parameterized routes go last to avoid shadowing) ---

@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeResponse:
    resume = await service.get_resume(current_user.id, resume_id)
    return ResumeResponse.model_validate(resume)


@router.put("/{resume_id}", response_model=ResumeResponse)
async def update_resume(
    resume_id: str,
    payload: ResumeUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeResponse:
    resume = await service.update_resume(current_user.id, resume_id, **payload.model_dump(exclude_unset=True))
    return ResumeResponse.model_validate(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> None:
    await service.delete_resume(current_user.id, resume_id)


@router.post("/{resume_id}/clone", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def clone_resume(
    resume_id: str,
    new_title: str | None = None,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeResponse:
    clone = await service.clone_resume(current_user.id, resume_id, new_title)
    return ResumeResponse.model_validate(clone)


@router.get("/{resume_id}/versions", response_model=list[ResumeResponse])
async def get_version_chain(
    resume_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> list[ResumeResponse]:
    chain = await service.get_version_chain(current_user.id, resume_id)
    return [ResumeResponse.model_validate(r) for r in chain]


@router.post("/{resume_id}/parse", response_model=ResumeParsedDetailResponse)
async def parse_resume(
    resume_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeParsedDetailResponse:
    resume = await service.parse_resume(current_user.id, resume_id)
    return ResumeParsedDetailResponse.model_validate(resume)


@router.post("/{resume_id}/ats-score", response_model=ATSScoreResponse)
async def score_ats(
    resume_id: str,
    payload: ATSScoreRequest,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ATSScoreResponse:
    report = await service.score_ats(current_user.id, resume_id, payload.job_description)
    return ATSScoreResponse.model_validate(report)


@router.post("/{resume_id}/match-job", response_model=JobMatchResponse)
async def match_job(
    resume_id: str,
    payload: JobMatchRequest,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> JobMatchResponse:
    match = await service.match_job(
        current_user.id, resume_id, payload.job_description, payload.job_role_title, payload.job_id
    )
    return JobMatchResponse.model_validate(match)


@router.post("/{resume_id}/optimize", response_model=ResumeOptimizeResponse)
async def optimize_resume(
    resume_id: str,
    payload: ResumeOptimizeRequest,
    current_user: User = Depends(get_current_active_user),
    service: ResumeService = Depends(get_resume_service),
) -> ResumeOptimizeResponse:
    result = await service.optimize_resume(current_user.id, resume_id, payload.target_job_description)
    return ResumeOptimizeResponse(**result)
