import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class JobTypeEnum(str, enum.Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class EmailStatusEnum(str, enum.Enum):
    APPLIED = "applied"
    UNDER_REVIEW = "under_review"
    SHORTLISTED = "shortlisted"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    ASSESSMENT_SENT = "assessment_sent"
    OFFER_RECEIVED = "offer_received"
    REJECTED = "rejected"
    NO_RESPONSE = "no_response"
    FOLLOW_UP_REQUIRED = "follow_up_required"


class InterviewTypeEnum(str, enum.Enum):
    HR = "hr"
    TECHNICAL = "technical"
    SYSTEM_DESIGN = "system_design"
    MANAGERIAL = "managerial"
    UNKNOWN = "unknown"


class MemoryTypeEnum(str, enum.Enum):
    APPLICATION = "application"
    RESUME_VERSION_USED = "resume_version_used"
    SUCCESSFUL_MATCH = "successful_match"
    REJECTED_ROLE = "rejected_role"
    INTERVIEW_HISTORY = "interview_history"


class PromptTemplate(Base):
    """Centralized, versioned prompt storage. All AI Engine call sites
    resolve their system/user prompts through PromptManager, which reads
    from this table (falling back to hardcoded defaults in prompts.py if
    no active DB override exists), so prompts can be tuned without a
    redeploy.
    """

    __tablename__ = "ai_prompt_templates"

    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    role_context: Mapped[str | None] = mapped_column(String(64), nullable=True)  # future: role-based customization
    locale: Mapped[str] = mapped_column(String(16), default="en", nullable=False)  # future: localization
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ab_test_group: Mapped[str | None] = mapped_column(String(32), nullable=True)  # future: A/B testing


class JobProfile(Base):
    """Structured output of the Job Intelligence Engine — a job description
    parsed into queryable fields, cached so re-matching against many
    resumes doesn't re-run extraction every time.
    """

    __tablename__ = "ai_job_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required_skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    preferred_skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    experience_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    salary_range: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    job_type: Mapped[JobTypeEnum] = mapped_column(
        SAEnum(JobTypeEnum, name="ai_job_type_enum"), default=JobTypeEnum.UNKNOWN, nullable=False
    )
    responsibilities: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    ats_keywords: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    hidden_requirements: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    provider_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_ai_response: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    matches: Mapped[list["ResumeMatchResult"]] = relationship(
        back_populates="job_profile", cascade="all, delete-orphan"
    )


class ResumeMatchResult(Base):
    """Output of the combined semantic + keyword + AI-reasoning matching
    engine, distinct from `resume.ResumeJobMatch` (which is the simpler
    single-shot AI match owned by the Resume module). This table is owned
    by the AI Core orchestrator and stores the weighted, multi-signal score.
    """

    __tablename__ = "ai_resume_match_results"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    job_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_job_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    match_score: Mapped[float] = mapped_column(Float, nullable=False)  # final weighted 0-100
    semantic_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    keyword_overlap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_reasoning_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    skill_overlap: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    missing_skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    risk_factors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)

    job_profile: Mapped["JobProfile"] = relationship(back_populates="matches")


class CoverLetterGeneration(Base):
    __tablename__ = "ai_cover_letters"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    job_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_job_profiles.id", ondelete="SET NULL"), nullable=True
    )
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tone: Mapped[str] = mapped_column(String(32), default="professional", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider_used: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ColdEmailGeneration(Base):
    __tablename__ = "ai_cold_emails"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_job_profiles.id", ondelete="SET NULL"), nullable=True
    )
    recruiter_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_used: Mapped[str | None] = mapped_column(String(32), nullable=True)


class EmailAnalysisResult(Base):
    """Output of the Email Analysis Engine: status classification +
    interview/rejection intelligence extracted from a single inbound email.
    """

    __tablename__ = "ai_email_analyses"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    raw_email_text: Mapped[str] = mapped_column(Text, nullable=False)

    status_classification: Mapped[EmailStatusEnum] = mapped_column(
        SAEnum(EmailStatusEnum, name="ai_email_status_enum"), nullable=False
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)

    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recruiter_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    interview_type: Mapped[InterviewTypeEnum | None] = mapped_column(
        SAEnum(InterviewTypeEnum, name="ai_interview_type_enum"), nullable=True
    )
    interview_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meeting_platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meeting_link: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interviewer_details: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    missing_skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    future_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)

    provider_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_ai_response: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AIMemoryEntry(Base):
    """Long-lived memory used to improve future decisions: which resume
    versions worked, which roles led to rejection, interview history, etc.
    Distinct from `ResumeSelectionLog` (audit trail) — this is the
    consolidated, queryable memory the AI Router reads from when building
    context for future requests.
    """

    __tablename__ = "ai_memory_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_type: Mapped[MemoryTypeEnum] = mapped_column(
        SAEnum(MemoryTypeEnum, name="ai_memory_type_enum"), nullable=False, index=True
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)  # short text injected into future prompt context
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)  # e.g. "success" | "failure" | None yet


class AICallLog(Base):
    """Observability log for every AI Router dispatch — used for the usage
    tracking / dashboard analytics the master prompt calls for, and to debug
    fallback behavior.
    """

    __tablename__ = "ai_call_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    providers_tried: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
