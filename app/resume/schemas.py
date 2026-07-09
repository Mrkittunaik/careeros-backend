"""Resume module schemas — MongoDB version.

Request/response shapes are unchanged from the Postgres version except
that every id field is now `str` instead of `uuid.UUID` (Mongo ids are
UUID-format strings, same convention as app.application/app.autoapply).
Field names, required/optional-ness, and validation constraints are
otherwise identical.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.resume.models import AIProviderEnum, ResumeFileTypeEnum, ResumeStatusEnum


# --- Resume core ---

class ResumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    file_url: str
    file_type: ResumeFileTypeEnum
    file_size_bytes: int | None
    skills_extracted: list
    experience_extracted: list
    education_extracted: list
    projects_extracted: list
    certifications: list
    ats_score: float | None
    status: ResumeStatusEnum
    failure_reason: str | None
    version_number: int
    parent_resume_id: str | None
    is_active: bool
    tags: list
    created_at: datetime
    updated_at: datetime


class ResumeListResponse(BaseModel):
    items: list[ResumeResponse]
    total: int
    limit: int
    offset: int


class ResumeUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = None
    is_active: bool | None = None


class ResumeParsedDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    raw_text: str | None
    parsed_json: dict
    skills_extracted: list
    experience_extracted: list
    education_extracted: list
    projects_extracted: list
    certifications: list


# --- AI analysis ---

class ResumeAIAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resume_id: str
    provider_used: AIProviderEnum
    classification: str | None
    experience_score: float | None
    strengths: list
    weaknesses: list
    rewrite_suggestions: list
    missing_skills: list
    created_at: datetime


# --- ATS scoring ---

class ATSScoreRequest(BaseModel):
    job_description: str | None = Field(default=None, max_length=20000)


class ATSScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resume_id: str
    score: float
    keyword_match_score: float | None
    skill_relevance_score: float | None
    experience_relevance_score: float | None
    format_compatibility_score: float | None
    readability_score: float | None
    missing_keywords: list
    suggestions: list
    created_at: datetime


# --- Job matching ---

class JobMatchRequest(BaseModel):
    job_description: str = Field(min_length=10, max_length=20000)
    job_role_title: str | None = Field(default=None, max_length=255)
    job_id: str | None = None


class JobMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resume_id: str
    job_role_title: str | None
    match_percentage: float
    skill_overlap: list
    missing_requirements: list
    experience_fit_score: float | None
    recommendation_score: float | None
    created_at: datetime


# --- Resume selection engine ---

class ResumeSelectionRequest(BaseModel):
    job_role_title: str = Field(min_length=1, max_length=255)
    job_description: str | None = Field(default=None, max_length=20000)


class ResumeSelectionResponse(BaseModel):
    selected_resume_id: str
    selection_method: str  # "rule" | "ai"
    match_percentage: float | None
    reasoning: str
    ranked_alternatives: list[dict]


class ResumeSelectionRuleCreateRequest(BaseModel):
    job_role_pattern: str = Field(min_length=1, max_length=255)
    resume_id: str
    priority: int = 0


class ResumeSelectionRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_role_pattern: str
    resume_id: str
    priority: int
    is_active: bool
    created_at: datetime


# --- Optimization ---

class ResumeOptimizeRequest(BaseModel):
    target_job_description: str | None = Field(default=None, max_length=20000)


class ResumeOptimizeResponse(BaseModel):
    rewritten_bullets: list[dict]
    ats_keyword_additions: list[str]
    formatting_suggestions: list[str]
    job_targeting_notes: str
    provider_used: str | None


# --- Search ---

class ResumeSearchRequest(BaseModel):
    query: str | None = Field(default=None, max_length=500)
    skill: str | None = None
    job_role: str | None = None
    min_ats_score: float | None = Field(default=None, ge=0, le=100)
    semantic: bool = False
    limit: int = Field(default=20, ge=1, le=100)


class ResumeSearchResult(BaseModel):
    resume_id: str
    title: str
    ats_score: float | None
    similarity_score: float | None = None
    tags: list


# --- BYOK AI provider keys ---

class AIProviderKeySetRequest(BaseModel):
    provider: AIProviderEnum
    api_key: str = Field(min_length=4, max_length=512)


class AIProviderKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: AIProviderEnum
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
