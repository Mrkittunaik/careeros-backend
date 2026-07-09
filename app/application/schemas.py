from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.application.constants import MAX_COMPANY_NAME_LENGTH, MAX_NOTE_LENGTH, MAX_ROLE_TITLE_LENGTH
from app.application.enums import (
    ApplicationPriorityEnum,
    ApplicationSortFieldEnum,
    ApplicationStatusEnum,
    AttachmentTypeEnum,
    SortDirectionEnum,
    TimelineEventTypeEnum,
)


# --- Core application ---

class ApplicationCreateRequest(BaseModel):
    company_name: str = Field(max_length=MAX_COMPANY_NAME_LENGTH)
    role_title: str = Field(max_length=MAX_ROLE_TITLE_LENGTH)
    job_url: str | None = Field(default=None, max_length=1024)
    job_description_text: str | None = None
    resume_id: str | None = None
    priority: ApplicationPriorityEnum = ApplicationPriorityEnum.MEDIUM
    portfolio_url: str | None = None
    github_url: str | None = None
    linkedin_url: str | None = None
    website_url: str | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)


class ApplicationUpdateRequest(BaseModel):
    company_name: str | None = Field(default=None, max_length=MAX_COMPANY_NAME_LENGTH)
    role_title: str | None = Field(default=None, max_length=MAX_ROLE_TITLE_LENGTH)
    job_url: str | None = Field(default=None, max_length=1024)
    job_description_text: str | None = None
    priority: ApplicationPriorityEnum | None = None
    portfolio_url: str | None = None
    github_url: str | None = None
    linkedin_url: str | None = None
    website_url: str | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    reminder_at: datetime | None = None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    company_name: str
    role_title: str
    job_url: str | None
    job_description_text: str | None
    job_profile_id: str | None
    resume_id: str | None
    cover_letter_id: str | None
    match_result_id: str | None
    status: ApplicationStatusEnum
    priority: ApplicationPriorityEnum
    ai_match_score: float | None
    portfolio_url: str | None
    github_url: str | None
    linkedin_url: str | None
    website_url: str | None
    metadata_json: dict
    applied_at: datetime | None
    reminder_at: datetime | None
    closed_at: datetime | None
    notes: str | None
    source: str
    source_site_url: str | None
    hr_email: str | None
    hr_email_sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApplicationListResponse(BaseModel):

    items: list[ApplicationResponse]
    total: int
    limit: int
    offset: int


class ApplicationSearchRequest(BaseModel):
    query: str | None = None
    status: list[ApplicationStatusEnum] | None = None
    priority: list[ApplicationPriorityEnum] | None = None
    company_name: str | None = None
    min_match_score: float | None = Field(default=None, ge=0, le=100)
    include_terminal: bool = True
    sort_by: ApplicationSortFieldEnum = ApplicationSortFieldEnum.UPDATED_AT
    sort_direction: SortDirectionEnum = SortDirectionEnum.DESC
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


# --- Status management ---

class ApplicationStatusUpdateRequest(BaseModel):
    status: ApplicationStatusEnum
    description: str | None = Field(default=None, max_length=1000)
    strict_transition: bool = False


# --- Timeline ---

class TimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: TimelineEventTypeEnum
    from_status: ApplicationStatusEnum | None
    to_status: ApplicationStatusEnum | None
    description: str | None
    event_metadata: dict
    created_at: datetime



# --- Resume selection / history ---

class ResumeSelectionForApplicationRequest(BaseModel):
    resume_id: str | None = None  # explicit choice; omit to trigger AI auto-selection
    use_ai_selection: bool = False


class ApplicationResumeHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resume_id: str
    resume_version_number: int | None
    selection_method: str
    match_score_at_selection: float | None
    was_active: bool
    created_at: datetime


# --- Cover letter / answers ---

class ApplicationCoverLetterGenerateRequest(BaseModel):
    tone: str = "professional"


class ApplicationAnswerGenerateRequest(BaseModel):
    question: str = Field(max_length=2000)
    word_limit: int | None = Field(default=None, ge=10, le=2000)


class ApplicationAnswerCreateRequest(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=10_000)


class ApplicationAnswerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    answer: str
    is_ai_generated: bool
    provider_used: str | None
    word_limit: int | None
    created_at: datetime


# --- Attachments ---

class ApplicationAttachmentCreateRequest(BaseModel):
    attachment_type: AttachmentTypeEnum
    label: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=1024)


class ApplicationAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    attachment_type: AttachmentTypeEnum
    label: str | None
    url: str | None
    storage_key: str | None
    created_at: datetime


# --- Package builder ---

class ApplicationPackageResponse(BaseModel):
    application: ApplicationResponse
    resume: dict | None
    cover_letter: dict | None
    answers: list[ApplicationAnswerResponse]
    attachments: list[ApplicationAttachmentResponse]
    is_complete: bool
    missing_items: list[str]


# --- Bot field-answer assist (bot-overlay) ---
# The desktop overlay bot scans a job application form and sends the
# detected fields here; backend fills in what it can from the user's
# profile/resume, and (once ai_core is Mongo-ready) asks AI for the rest.

class BotFieldRequest(BaseModel):
    index: int
    tag: str
    type: str | None = None
    name: str | None = None
    question: str
    required: bool = False


class BotAnswersRequest(BaseModel):
    job_url: str
    job_title: str | None = None
    company_name: str | None = None
    fields: list[BotFieldRequest]


class BotAnswersResponse(BaseModel):
    answers: dict[str, str]  # { "0": "answer text", "2": "answer text" }, keyed by field index as string
    resume_file_id: str | None = None
    resume_file_name: str | None = None
    resume_download_url: str | None = None
    unanswered_required: list[int] = []  # indices of required fields we couldn't fill - bot should flag/skip these


# --- Job agent integration ---
# Submitted by the local Playwright job agent (see /job_agent) after it
# applies to a job on the user's behalf.

class AgentApplicationSubmitRequest(BaseModel):
    company_name: str = Field(max_length=MAX_COMPANY_NAME_LENGTH)
    role_title: str = Field(max_length=MAX_ROLE_TITLE_LENGTH)
    job_url: str | None = Field(default=None, max_length=1024)
    job_description_text: str | None = None
    source_site_url: str = Field(max_length=2048)
    hr_email: str | None = Field(default=None, max_length=320)
