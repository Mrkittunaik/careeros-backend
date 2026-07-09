import enum


class EmailProviderEnum(str, enum.Enum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    IMAP = "imap"


class EmailAccountStatusEnum(str, enum.Enum):
    CONNECTED = "connected"
    SYNCING = "syncing"
    PAUSED = "paused"
    AUTH_EXPIRED = "auth_expired"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class EmailClassificationEnum(str, enum.Enum):
    """AI classification labels per the Part 6 spec's Email Classification Engine."""

    APPLICATION_SUBMITTED_CONFIRMATION = "application_submitted_confirmation"
    UNDER_REVIEW = "under_review"
    SHORTLISTED = "shortlisted"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    ASSESSMENT_REQUEST = "assessment_request"
    OFFER_RECEIVED = "offer_received"
    REJECTION = "rejection"
    FOLLOW_UP_REQUEST = "follow_up_request"
    GENERAL_RECRUITER_MESSAGE = "general_recruiter_message"
    UNKNOWN = "unknown"


# Email classification -> application status mapping, per spec's Status
# Tracking Engine. Values are ApplicationStatusEnum.value strings (kept as
# strings here to avoid a hard import dependency between modules).
CLASSIFICATION_TO_APPLICATION_STATUS: dict[str, str] = {
    EmailClassificationEnum.UNDER_REVIEW.value: "under_review",
    EmailClassificationEnum.SHORTLISTED.value: "under_review",
    EmailClassificationEnum.INTERVIEW_SCHEDULED.value: "interview",
    EmailClassificationEnum.ASSESSMENT_REQUEST.value: "assessment",
    EmailClassificationEnum.OFFER_RECEIVED.value: "offer",
    EmailClassificationEnum.REJECTION.value: "rejected",
}

# Classifications that should never move an application backwards (used by
# the matching/status engine to avoid regressing e.g. OFFER -> UNDER_REVIEW).
NON_REGRESSIVE_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        EmailClassificationEnum.UNDER_REVIEW.value,
        EmailClassificationEnum.SHORTLISTED.value,
    }
)


class EmailFolderCategoryEnum(str, enum.Enum):
    """Coarse pre-filter bucket applied before AI classification, per the
    spec's Email Filtering Rules section."""

    JOB_RELATED = "job_related"
    NEWSLETTER = "newsletter"
    PROMOTION = "promotion"
    SPAM = "spam"
    UNRELATED = "unrelated"


class InterviewPlatformEnum(str, enum.Enum):
    ZOOM = "zoom"
    GOOGLE_MEET = "google_meet"
    MICROSOFT_TEAMS = "microsoft_teams"
    PHONE = "phone"
    IN_PERSON = "in_person"
    OTHER = "other"
    UNKNOWN = "unknown"


class SyncJobStatusEnum(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SyncTriggerEnum(str, enum.Enum):
    INITIAL_IMPORT = "initial_import"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"
    MANUAL = "manual"
