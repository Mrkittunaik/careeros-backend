"""Application module — MongoDB version.

Converted from SQLAlchemy/Postgres (old version kept as
models.py.postgres.bak for reference). The old design used four separate
relational tables (applications, application_timeline_events,
application_resume_history, application_answers, application_attachments)
joined by foreign keys. In Mongo, everything that was always fetched
*with* the application (timeline, answers, attachments, resume history) is
embedded as sub-documents on a single `applications` collection — this
matches how the API actually reads/writes them (always as one aggregate)
and avoids N+1 lookups. Collection: applications.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.application.enums import (
    ApplicationPriorityEnum,
    ApplicationStatusEnum,
    AttachmentTypeEnum,
    TimelineEventTypeEnum,
)
from app.core.mongo_base import MongoDocument, new_id, utcnow


class ApplicationTimelineEvent(BaseModel):
    """Embedded sub-document. Append-only — nothing here should ever be
    mutated after insert, only appended via $push.
    """

    id: str = Field(default_factory=new_id)
    event_type: TimelineEventTypeEnum
    from_status: ApplicationStatusEnum | None = None
    to_status: ApplicationStatusEnum | None = None
    description: str | None = None
    event_metadata: dict = Field(default_factory=dict)
    actor_user_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ApplicationResumeHistory(BaseModel):
    """Embedded sub-document. Records every resume ever attached, not
    just the current one.
    """

    id: str = Field(default_factory=new_id)
    resume_id: str
    resume_version_number: int | None = None
    selection_method: str = "manual"  # "manual" | "ai"
    match_score_at_selection: float | None = None
    was_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class ApplicationAnswer(BaseModel):
    """Embedded sub-document. A single Q&A pair for application-form
    questions.
    """

    id: str = Field(default_factory=new_id)
    question: str
    answer: str
    is_ai_generated: bool = True
    provider_used: str | None = None
    word_limit: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ApplicationAttachment(BaseModel):
    """Embedded sub-document. Supplementary links/files. The four
    "primary" links are also mirrored as top-level fields on Application
    for fast access without scanning this list.
    """

    id: str = Field(default_factory=new_id)
    attachment_type: AttachmentTypeEnum
    label: str | None = None
    url: str | None = None
    storage_key: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Application(MongoDocument):
    """A single job application and its current package/state.
    Collection: applications.

    job_profile_id / resume_id / cover_letter_id / match_result_id are
    references into other modules' collections, stored as plain string
    ids (Mongo has no cross-collection FK enforcement — validity is
    checked at the service layer when set, same as the old
    ondelete=SET NULL columns implied "best effort" referential integrity).
    """

    user_id: str

    company_name: str
    role_title: str
    job_url: str | None = None
    job_description_text: str | None = None

    job_profile_id: str | None = None
    resume_id: str | None = None
    cover_letter_id: str | None = None
    match_result_id: str | None = None

    status: ApplicationStatusEnum = ApplicationStatusEnum.DRAFT
    priority: ApplicationPriorityEnum = ApplicationPriorityEnum.MEDIUM

    ai_match_score: float | None = None

    portfolio_url: str | None = None
    github_url: str | None = None
    linkedin_url: str | None = None
    website_url: str | None = None
    metadata_json: dict = Field(default_factory=dict)

    applied_at: datetime | None = None
    reminder_at: datetime | None = None
    closed_at: datetime | None = None

    notes: str | None = None

    # --- Source of the application: manual (dashboard) vs the local
    # Playwright agent. Lets the dashboard show "Applied by bot" and lets
    # the agent's writes be told apart from user-entered applications. ---
    source: str = "manual"  # "manual" | "agent"
    source_site_url: str | None = None  # the job board URL the agent scanned
    hr_email: str | None = None  # captured by the agent's scan step, if found
    hr_email_sent_at: datetime | None = None

    timeline_events: list[ApplicationTimelineEvent] = Field(default_factory=list)
    answers: list[ApplicationAnswer] = Field(default_factory=list)
    attachments: list[ApplicationAttachment] = Field(default_factory=list)
    resume_history: list[ApplicationResumeHistory] = Field(default_factory=list)
