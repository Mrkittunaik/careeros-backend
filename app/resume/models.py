"""Resume module — MongoDB version.

Converted from SQLAlchemy/Postgres (old version kept as
models.py.postgres.bak for reference). The old schema was one `resumes`
table plus four related tables (resume_ai_analyses, resume_ats_reports,
resume_job_matches, resume_selection_rules, resume_selection_logs) and a
separate user_ai_provider_keys table.

Design decisions, following the precedent set by app/application (embed
what's always fetched together) and app/autoapply (separate collection
for high-volume/independently-queried history):

- `Resume` is its own document. Collection: resumes.
- `ResumeAIAnalysis`, `ResumeATSReport`, and `ResumeJobMatch` were always
  queried independently of the parent Resume (e.g. "get latest ATS report
  for this resume", "list job matches for this resume") and can grow
  unbounded as append-only logs, exactly like ActivityLogEntry in
  app.autoapply — so each becomes its own collection referenced by a
  plain string `resume_id`, not an embedded list on Resume.
- `ResumeSelectionRule` and `ResumeSelectionLog` were already independent
  tables (rules are CRUD'd on their own; logs are an append-only audit
  trail queried by resume_id for success-rate computation) -> separate
  collections, unchanged in shape.
- `UserAIProviderKey` was already independent (queried by user_id +
  provider, upserted) -> separate collection, unchanged in shape.
"""

import enum
from datetime import datetime

from app.core.mongo_base import MongoDocument


class ResumeFileTypeEnum(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"


class ResumeStatusEnum(str, enum.Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"


class AIProviderEnum(str, enum.Enum):
    GROQ = "groq"
    OPENAI = "openai"
    GEMINI = "gemini"
    CLAUDE = "claude"
    OLLAMA = "ollama"


class Resume(MongoDocument):
    """A single resume document. Multiple resumes per user; versions form a
    chain via `parent_resume_id` so a user can track "Resume v1 -> v2 -> v3"
    without losing history. Collection: resumes.
    """

    user_id: str

    title: str
    file_url: str
    file_type: ResumeFileTypeEnum
    file_size_bytes: int | None = None
    storage_key: str

    raw_text: str | None = None
    parsed_json: dict = {}

    skills_extracted: list = []
    experience_extracted: list = []
    education_extracted: list = []
    projects_extracted: list = []
    certifications: list = []

    embedding_id: str | None = None  # ChromaDB doc id
    ats_score: float | None = None

    status: ResumeStatusEnum = ResumeStatusEnum.UPLOADED
    failure_reason: str | None = None

    version_number: int = 1
    parent_resume_id: str | None = None
    is_active: bool = True
    tags: list = []


class ResumeAIAnalysis(MongoDocument):
    """Snapshot of AI-driven analysis for a resume: classification, scoring,
    rewrite suggestions. Append-only log, own collection (queried
    independently by resume_id, same pattern as ActivityLogEntry).
    Collection: resume_ai_analyses.
    """

    resume_id: str
    provider_used: AIProviderEnum
    classification: str | None = None  # e.g. "Backend Developer"
    experience_score: float | None = None
    strengths: list = []
    weaknesses: list = []
    rewrite_suggestions: list = []
    missing_skills: list = []
    raw_response: dict = {}


class ResumeATSReport(MongoDocument):
    """A single ATS scoring run, optionally against a specific job
    description. Own collection. Collection: resume_ats_reports.
    """

    resume_id: str
    job_description_text: str | None = None
    score: float
    keyword_match_score: float | None = None
    skill_relevance_score: float | None = None
    experience_relevance_score: float | None = None
    format_compatibility_score: float | None = None
    readability_score: float | None = None
    missing_keywords: list = []
    suggestions: list = []


class ResumeJobMatch(MongoDocument):
    """Result of matching a resume against a specific job description/
    posting. Own collection. Collection: resume_job_matches.
    """

    resume_id: str
    job_id: str | None = None
    job_description_text: str
    job_role_title: str | None = None

    match_percentage: float
    skill_overlap: list = []
    missing_requirements: list = []
    experience_fit_score: float | None = None
    recommendation_score: float | None = None


class ResumeSelectionRule(MongoDocument):
    """User-defined override rules: IF job_role = X -> use Resume Y.
    Evaluated before AI auto-selection in the Resume Selection Engine.
    Collection: resume_selection_rules.
    """

    user_id: str
    job_role_pattern: str  # matched case-insensitively / substring
    resume_id: str
    priority: int = 0  # higher = evaluated first
    is_active: bool = True


class ResumeSelectionLog(MongoDocument):
    """Audit trail of every automated resume selection decision — used to
    compute "past success rate" per resume over time.
    Collection: resume_selection_logs.
    """

    user_id: str
    resume_id: str
    job_role_title: str | None = None
    selection_method: str  # "rule" | "ai"
    match_percentage: float | None = None
    was_successful: bool | None = None  # updated later by application outcome


class UserAIProviderKey(MongoDocument):
    """User-supplied API keys for AI providers (BYOK). Encrypted at rest via
    AES-256-GCM (app.core.security.encrypt_secret). If a user has no key set
    for a provider, the system falls back to the platform-level key/provider
    priority configured in Settings. Collection: user_ai_provider_keys.
    """

    user_id: str
    provider: AIProviderEnum
    encrypted_api_key: str
    is_active: bool = True
    last_used_at: datetime | None = None
