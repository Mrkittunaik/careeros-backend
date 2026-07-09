import enum


class ApplicationStatusEnum(str, enum.Enum):
    """Full lifecycle of a job application, from local draft through to
    a terminal outcome. `Every status change must create a timeline event`
    per the Part 5A spec — enforced in ApplicationService, not here.
    """

    DRAFT = "draft"
    PREPARED = "prepared"
    READY = "ready"
    SUBMITTED = "submitted"
    APPLIED = "applied"
    VIEWED = "viewed"
    UNDER_REVIEW = "under_review"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"
    ARCHIVED = "archived"


# Statuses that represent a "finished" application — used to gate certain
# mutations (e.g. you cannot re-submit a withdrawn application) and to
# exclude from default active-application listings.
TERMINAL_STATUSES: frozenset[ApplicationStatusEnum] = frozenset(
    {
        ApplicationStatusEnum.ACCEPTED,
        ApplicationStatusEnum.REJECTED,
        ApplicationStatusEnum.WITHDRAWN,
        ApplicationStatusEnum.CLOSED,
        ApplicationStatusEnum.ARCHIVED,
    }
)

# Allowed forward/lateral transitions. Not strictly enforced by default
# (recruiting is messy — statuses can jump around), but used by
# `validators.py` for the optional strict-mode check and to build the
# "next likely statuses" hint returned to the frontend.
STATUS_TRANSITIONS: dict[ApplicationStatusEnum, frozenset[ApplicationStatusEnum]] = {
    ApplicationStatusEnum.DRAFT: frozenset({ApplicationStatusEnum.PREPARED, ApplicationStatusEnum.ARCHIVED}),
    ApplicationStatusEnum.PREPARED: frozenset(
        {ApplicationStatusEnum.READY, ApplicationStatusEnum.DRAFT, ApplicationStatusEnum.ARCHIVED}
    ),
    ApplicationStatusEnum.READY: frozenset(
        {ApplicationStatusEnum.SUBMITTED, ApplicationStatusEnum.PREPARED, ApplicationStatusEnum.ARCHIVED}
    ),
    ApplicationStatusEnum.SUBMITTED: frozenset(
        {ApplicationStatusEnum.APPLIED, ApplicationStatusEnum.WITHDRAWN}
    ),
    ApplicationStatusEnum.APPLIED: frozenset(
        {
            ApplicationStatusEnum.VIEWED,
            ApplicationStatusEnum.UNDER_REVIEW,
            ApplicationStatusEnum.REJECTED,
            ApplicationStatusEnum.WITHDRAWN,
        }
    ),
    ApplicationStatusEnum.VIEWED: frozenset(
        {ApplicationStatusEnum.UNDER_REVIEW, ApplicationStatusEnum.REJECTED, ApplicationStatusEnum.WITHDRAWN}
    ),
    ApplicationStatusEnum.UNDER_REVIEW: frozenset(
        {
            ApplicationStatusEnum.ASSESSMENT,
            ApplicationStatusEnum.INTERVIEW,
            ApplicationStatusEnum.REJECTED,
            ApplicationStatusEnum.WITHDRAWN,
        }
    ),
    ApplicationStatusEnum.ASSESSMENT: frozenset(
        {ApplicationStatusEnum.INTERVIEW, ApplicationStatusEnum.REJECTED, ApplicationStatusEnum.WITHDRAWN}
    ),
    ApplicationStatusEnum.INTERVIEW: frozenset(
        {
            ApplicationStatusEnum.INTERVIEW,
            ApplicationStatusEnum.OFFER,
            ApplicationStatusEnum.REJECTED,
            ApplicationStatusEnum.WITHDRAWN,
        }
    ),
    ApplicationStatusEnum.OFFER: frozenset(
        {ApplicationStatusEnum.ACCEPTED, ApplicationStatusEnum.REJECTED, ApplicationStatusEnum.WITHDRAWN}
    ),
    ApplicationStatusEnum.ACCEPTED: frozenset({ApplicationStatusEnum.CLOSED}),
    ApplicationStatusEnum.REJECTED: frozenset({ApplicationStatusEnum.ARCHIVED}),
    ApplicationStatusEnum.WITHDRAWN: frozenset({ApplicationStatusEnum.ARCHIVED}),
    ApplicationStatusEnum.CLOSED: frozenset({ApplicationStatusEnum.ARCHIVED}),
    ApplicationStatusEnum.ARCHIVED: frozenset(),
}


class ApplicationPriorityEnum(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TimelineEventTypeEnum(str, enum.Enum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    RESUME_SELECTED = "resume_selected"
    RESUME_CHANGED = "resume_changed"
    COVER_LETTER_GENERATED = "cover_letter_generated"
    ANSWER_GENERATED = "answer_generated"
    PACKAGE_BUILT = "package_built"
    NOTE_ADDED = "note_added"
    ATTACHMENT_ADDED = "attachment_added"
    ATTACHMENT_REMOVED = "attachment_removed"
    REMINDER_SET = "reminder_set"
    UPDATED = "updated"
    DELETED = "deleted"


class AttachmentTypeEnum(str, enum.Enum):
    PORTFOLIO = "portfolio"
    GITHUB = "github"
    LINKEDIN = "linkedin"
    WEBSITE = "website"
    OTHER = "other"


class ApplicationSortFieldEnum(str, enum.Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    STATUS = "status"
    PRIORITY = "priority"
    MATCH_SCORE = "match_score"
    COMPANY_NAME = "company_name"
    APPLIED_AT = "applied_at"


class SortDirectionEnum(str, enum.Enum):
    ASC = "asc"
    DESC = "desc"
