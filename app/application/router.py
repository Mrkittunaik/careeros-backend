
from fastapi import APIRouter, Depends, Query, status

from app.application.dependencies import get_application_service
from app.application.enums import (
    ApplicationPriorityEnum,
    ApplicationSortFieldEnum,
    ApplicationStatusEnum,
    SortDirectionEnum,
)
from app.application.schemas import (
    AgentApplicationSubmitRequest,
    ApplicationAnswerCreateRequest,
    ApplicationAnswerGenerateRequest,
    ApplicationAnswerResponse,
    ApplicationAttachmentCreateRequest,
    ApplicationAttachmentResponse,
    ApplicationCoverLetterGenerateRequest,
    ApplicationCreateRequest,
    ApplicationListResponse,
    ApplicationPackageResponse,
    ApplicationResponse,
    ApplicationResumeHistoryResponse,
    ApplicationSearchRequest,
    ApplicationStatusUpdateRequest,
    ApplicationUpdateRequest,
    BotAnswersRequest,
    BotAnswersResponse,
    ResumeSelectionForApplicationRequest,
    TimelineEventResponse,
)
from app.application.service import ApplicationService
from app.auth.dependencies import get_current_active_user
from app.auth.models import User

router = APIRouter(prefix="/applications", tags=["Application Management"])


# --- Core CRUD ---

@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationResponse:
    application = await service.create_application(current_user.id, **payload.model_dump())
    return ApplicationResponse.model_validate(application)


@router.post("/agent-submit", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def submit_from_agent(
    payload: AgentApplicationSubmitRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationResponse:
    """Called by the local Playwright job agent (see /job_agent) once it
    has applied to a job on the authenticated user's behalf. Creates the
    Application already in APPLIED status, source='agent'.
    """
    application = await service.create_from_agent(
        current_user.id,
        company_name=payload.company_name,
        role_title=payload.role_title,
        job_url=payload.job_url,
        job_description_text=payload.job_description_text,
        source_site_url=payload.source_site_url,
        hr_email=payload.hr_email,
    )
    return ApplicationResponse.model_validate(application)


@router.post("/bot/answers", response_model=BotAnswersResponse)
async def get_bot_answers(
    payload: BotAnswersRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> BotAnswersResponse:
    """Called by the local bot-overlay while it's scanning a job
    application form. Returns direct-profile-match answers immediately;
    AI-generated answers for open-ended questions will be added once
    app.ai_core is converted to MongoDB (see service.get_bot_field_answers).
    """
    result = await service.get_bot_field_answers(
        current_user.id,
        job_url=payload.job_url,
        job_title=payload.job_title,
        company_name=payload.company_name,
        fields=[f.model_dump() for f in payload.fields],
    )
    return BotAnswersResponse(**result)


@router.post("/search", response_model=ApplicationListResponse)
async def search_applications(
    payload: ApplicationSearchRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationListResponse:
    applications, total = await service.search_applications(
        current_user.id,
        query=payload.query,
        statuses=payload.status,
        priorities=payload.priority,
        company_name=payload.company_name,
        min_match_score=payload.min_match_score,
        include_terminal=payload.include_terminal,
        sort_by=payload.sort_by,
        sort_direction=payload.sort_direction,
        limit=payload.limit,
        offset=payload.offset,
    )
    return ApplicationListResponse(
        items=[ApplicationResponse.model_validate(a) for a in applications],
        total=total,
        limit=payload.limit,
        offset=payload.offset,
    )


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    status_filter: list[ApplicationStatusEnum] | None = Query(default=None, alias="status"),
    priority: list[ApplicationPriorityEnum] | None = Query(default=None),
    company_name: str | None = Query(default=None),
    include_terminal: bool = Query(default=True),
    sort_by: ApplicationSortFieldEnum = Query(default=ApplicationSortFieldEnum.UPDATED_AT),
    sort_direction: SortDirectionEnum = Query(default=SortDirectionEnum.DESC),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationListResponse:
    applications, total = await service.search_applications(
        current_user.id,
        statuses=status_filter,
        priorities=priority,
        company_name=company_name,
        include_terminal=include_terminal,
        sort_by=sort_by,
        sort_direction=sort_direction,
        limit=limit,
        offset=offset,
    )
    return ApplicationListResponse(
        items=[ApplicationResponse.model_validate(a) for a in applications], total=total, limit=limit, offset=offset
    )


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationResponse:
    application = await service.get_application(current_user.id, application_id)
    return ApplicationResponse.model_validate(application)


@router.put("/{application_id}", response_model=ApplicationResponse)
async def update_application(
    application_id: str,
    payload: ApplicationUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationResponse:
    application = await service.update_application(
        current_user.id, application_id, **payload.model_dump(exclude_unset=True)
    )
    return ApplicationResponse.model_validate(application)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    application_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> None:
    await service.delete_application(current_user.id, application_id)


# --- Status management ---

@router.put("/{application_id}/status", response_model=ApplicationResponse)
async def update_status(
    application_id: str,
    payload: ApplicationStatusUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationResponse:
    application = await service.update_status(
        current_user.id,
        application_id,
        payload.status,
        description=payload.description,
        strict_transition=payload.strict_transition,
    )
    return ApplicationResponse.model_validate(application)


@router.get("/{application_id}/timeline", response_model=list[TimelineEventResponse])
async def get_timeline(
    application_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> list[TimelineEventResponse]:
    events = await service.get_timeline(current_user.id, application_id)
    return [TimelineEventResponse.model_validate(e) for e in events]


# --- Resume selection / history ---

@router.post("/{application_id}/resume", response_model=ApplicationResponse)
async def select_resume(
    application_id: str,
    payload: ResumeSelectionForApplicationRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationResponse:
    application = await service.select_resume(
        current_user.id,
        application_id,
        resume_id=payload.resume_id,
        use_ai_selection=payload.use_ai_selection,
    )
    return ApplicationResponse.model_validate(application)


@router.get("/{application_id}/resume-history", response_model=list[ApplicationResumeHistoryResponse])
async def get_resume_history(
    application_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> list[ApplicationResumeHistoryResponse]:
    history = await service.get_resume_history(current_user.id, application_id)
    return [ApplicationResumeHistoryResponse.model_validate(h) for h in history]


# --- Cover letter integration ---

@router.post("/{application_id}/cover-letter", response_model=ApplicationResponse)
async def generate_cover_letter(
    application_id: str,
    payload: ApplicationCoverLetterGenerateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationResponse:
    application = await service.generate_cover_letter(current_user.id, application_id, tone=payload.tone)
    return ApplicationResponse.model_validate(application)


# --- AI answer generation ---

@router.post("/{application_id}/answers/generate", response_model=ApplicationAnswerResponse, status_code=status.HTTP_201_CREATED)
async def generate_answer(
    application_id: str,
    payload: ApplicationAnswerGenerateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationAnswerResponse:
    answer = await service.generate_answer(
        current_user.id, application_id, question=payload.question, word_limit=payload.word_limit
    )
    return ApplicationAnswerResponse.model_validate(answer)


@router.post("/{application_id}/answers", response_model=ApplicationAnswerResponse, status_code=status.HTTP_201_CREATED)
async def add_manual_answer(
    application_id: str,
    payload: ApplicationAnswerCreateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationAnswerResponse:
    answer = await service.add_manual_answer(
        current_user.id, application_id, question=payload.question, answer=payload.answer
    )
    return ApplicationAnswerResponse.model_validate(answer)


@router.get("/{application_id}/answers", response_model=list[ApplicationAnswerResponse])
async def list_answers(
    application_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> list[ApplicationAnswerResponse]:
    answers = await service.list_answers(current_user.id, application_id)
    return [ApplicationAnswerResponse.model_validate(a) for a in answers]


@router.delete("/{application_id}/answers/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_answer(
    application_id: str,
    answer_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> None:
    await service.delete_answer(current_user.id, application_id, answer_id)


# --- Attachments ---

@router.post("/{application_id}/attachments", response_model=ApplicationAttachmentResponse, status_code=status.HTTP_201_CREATED)
async def add_attachment(
    application_id: str,
    payload: ApplicationAttachmentCreateRequest,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationAttachmentResponse:
    attachment = await service.add_attachment(current_user.id, application_id, **payload.model_dump())
    return ApplicationAttachmentResponse.model_validate(attachment)


@router.get("/{application_id}/attachments", response_model=list[ApplicationAttachmentResponse])
async def list_attachments(
    application_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> list[ApplicationAttachmentResponse]:
    attachments = await service.list_attachments(current_user.id, application_id)
    return [ApplicationAttachmentResponse.model_validate(a) for a in attachments]


@router.delete("/{application_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_attachment(
    application_id: str,
    attachment_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> None:
    await service.remove_attachment(current_user.id, application_id, attachment_id)


# --- Package builder ---

@router.get("/{application_id}/package", response_model=ApplicationPackageResponse)
async def build_package(
    application_id: str,
    current_user: User = Depends(get_current_active_user),
    service: ApplicationService = Depends(get_application_service),
) -> ApplicationPackageResponse:
    result = await service.build_package(current_user.id, application_id)
    return ApplicationPackageResponse(
        application=ApplicationResponse.model_validate(result["application"]),
        resume=result["resume"],
        cover_letter=result["cover_letter"],
        answers=[ApplicationAnswerResponse.model_validate(a) for a in result["answers"]],
        attachments=[ApplicationAttachmentResponse.model_validate(a) for a in result["attachments"]],
        is_complete=result["is_complete"],
        missing_items=result["missing_items"],
    )
