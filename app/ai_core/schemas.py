import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.ai_core.models import EmailStatusEnum, InterviewTypeEnum, JobTypeEnum


# --- Job Intelligence ---

class JobAnalyzeRequest(BaseModel):
    job_description: str = Field(min_length=10, max_length=20000)
    source_job_id: uuid.UUID | None = None


class JobProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    company: str | None
    required_skills: list
    preferred_skills: list
    experience_level: str | None
    salary_range: dict
    job_type: JobTypeEnum
    responsibilities: list
    ats_keywords: list
    hidden_requirements: list
    provider_used: str | None
    created_at: datetime


# --- Matching ---

class MatchRequest(BaseModel):
    resume_id: uuid.UUID
    job_profile_id: uuid.UUID


class RankResumesRequest(BaseModel):
    job_profile_id: uuid.UUID
    resume_ids: list[uuid.UUID] | None = None  # None = all of the user's resumes


class ResumeMatchResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resume_id: uuid.UUID
    job_profile_id: uuid.UUID
    match_score: float
    semantic_similarity: float | None
    keyword_overlap_pct: float | None
    ai_reasoning_score: float | None
    skill_overlap: list
    missing_skills: list
    risk_factors: list
    recommendation: str | None
    created_at: datetime


# --- Cover letter ---

class CoverLetterRequest(BaseModel):
    resume_id: uuid.UUID
    company_name: str = Field(min_length=1, max_length=255)
    role_title: str = Field(min_length=1, max_length=255)
    job_description: str | None = Field(default=None, max_length=20000)
    tone: str = "professional"
    job_profile_id: uuid.UUID | None = None


class CoverLetterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resume_id: uuid.UUID | None
    company_name: str | None
    role_title: str | None
    tone: str
    content: str
    provider_used: str | None
    created_at: datetime


# --- Cold email ---

class ColdEmailRequest(BaseModel):
    resume_id: uuid.UUID
    role_title: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    recruiter_name: str | None = None
    recruiter_title: str | None = None
    job_profile_id: uuid.UUID | None = None


class ColdEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recruiter_name: str | None
    company_name: str | None
    role_title: str | None
    subject: str
    body: str
    follow_up_body: str | None
    provider_used: str | None
    created_at: datetime


# --- Email analysis ---

class EmailAnalyzeRequest(BaseModel):
    email_text: str = Field(min_length=1, max_length=20000)
    source_email_id: uuid.UUID | None = None


class EmailAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status_classification: EmailStatusEnum
    confidence_score: float
    company_name: str | None
    job_title: str | None
    recruiter_name: str | None
    interview_type: InterviewTypeEnum | None
    interview_datetime: datetime | None
    meeting_platform: str | None
    meeting_link: str | None
    duration_minutes: int | None
    interviewer_details: list
    rejection_reason: str | None
    missing_skills: list
    feedback: str | None
    future_recommendation: str | None
    provider_used: str | None
    created_at: datetime


# --- Usage / analytics ---

class AIUsageSummaryResponse(BaseModel):
    total_calls: int
    success_rate: float | None
    cache_hit_rate: float | None
    provider_distribution: dict
