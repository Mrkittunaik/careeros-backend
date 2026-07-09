import enum


class NotificationPriorityEnum(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class NotificationCategoryEnum(str, enum.Enum):
    APPLICATION = "application"
    INTERVIEW = "interview"
    ASSESSMENT = "assessment"
    OFFER = "offer"
    REJECTION = "rejection"
    RECRUITER = "recruiter"
    RESUME = "resume"
    AI_RECOMMENDATION = "ai_recommendation"
    SCHEDULER = "scheduler"
    AUTOMATION = "automation"
    SECURITY = "security"
    SYSTEM = "system"


class NotificationStatusEnum(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    DISMISSED = "dismissed"


class DeliveryMethodEnum(str, enum.Enum):
    IN_APP = "in_app"
    PUSH = "push"
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    DESKTOP = "desktop"
    WEBSOCKET = "websocket"


class DeliveryStatusEnum(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


# Default delivery methods fired per category unless the user's preferences
# (NotificationPreference) narrow them down. Mirrors the spec's "One event
# may trigger: Dashboard, Push, Email, WebSocket" guidance.
DEFAULT_DELIVERY_METHODS: dict[NotificationCategoryEnum, frozenset[DeliveryMethodEnum]] = {
    NotificationCategoryEnum.APPLICATION: frozenset({DeliveryMethodEnum.IN_APP, DeliveryMethodEnum.WEBSOCKET}),
    NotificationCategoryEnum.INTERVIEW: frozenset(
        {DeliveryMethodEnum.IN_APP, DeliveryMethodEnum.WEBSOCKET, DeliveryMethodEnum.PUSH, DeliveryMethodEnum.EMAIL}
    ),
    NotificationCategoryEnum.ASSESSMENT: frozenset(
        {DeliveryMethodEnum.IN_APP, DeliveryMethodEnum.WEBSOCKET, DeliveryMethodEnum.PUSH}
    ),
    NotificationCategoryEnum.OFFER: frozenset(
        {DeliveryMethodEnum.IN_APP, DeliveryMethodEnum.WEBSOCKET, DeliveryMethodEnum.PUSH, DeliveryMethodEnum.EMAIL}
    ),
    NotificationCategoryEnum.REJECTION: frozenset({DeliveryMethodEnum.IN_APP, DeliveryMethodEnum.WEBSOCKET}),
    NotificationCategoryEnum.RECRUITER: frozenset(
        {DeliveryMethodEnum.IN_APP, DeliveryMethodEnum.WEBSOCKET, DeliveryMethodEnum.PUSH}
    ),
    NotificationCategoryEnum.RESUME: frozenset({DeliveryMethodEnum.IN_APP}),
    NotificationCategoryEnum.AI_RECOMMENDATION: frozenset({DeliveryMethodEnum.IN_APP}),
    NotificationCategoryEnum.SCHEDULER: frozenset({DeliveryMethodEnum.IN_APP}),
    NotificationCategoryEnum.AUTOMATION: frozenset({DeliveryMethodEnum.IN_APP, DeliveryMethodEnum.WEBSOCKET}),
    NotificationCategoryEnum.SECURITY: frozenset(
        {DeliveryMethodEnum.IN_APP, DeliveryMethodEnum.WEBSOCKET, DeliveryMethodEnum.EMAIL}
    ),
    NotificationCategoryEnum.SYSTEM: frozenset({DeliveryMethodEnum.IN_APP}),
}

# Category -> priority used when a caller doesn't specify one explicitly,
# per the spec's worked examples (Interview Invitation -> CRITICAL, etc).
DEFAULT_PRIORITY_BY_CATEGORY: dict[NotificationCategoryEnum, NotificationPriorityEnum] = {
    NotificationCategoryEnum.INTERVIEW: NotificationPriorityEnum.CRITICAL,
    NotificationCategoryEnum.OFFER: NotificationPriorityEnum.CRITICAL,
    NotificationCategoryEnum.ASSESSMENT: NotificationPriorityEnum.HIGH,
    NotificationCategoryEnum.APPLICATION: NotificationPriorityEnum.NORMAL,
    NotificationCategoryEnum.REJECTION: NotificationPriorityEnum.NORMAL,
    NotificationCategoryEnum.RECRUITER: NotificationPriorityEnum.HIGH,
    NotificationCategoryEnum.RESUME: NotificationPriorityEnum.LOW,
    NotificationCategoryEnum.AI_RECOMMENDATION: NotificationPriorityEnum.LOW,
    NotificationCategoryEnum.SCHEDULER: NotificationPriorityEnum.LOW,
    NotificationCategoryEnum.AUTOMATION: NotificationPriorityEnum.NORMAL,
    NotificationCategoryEnum.SECURITY: NotificationPriorityEnum.URGENT,
    NotificationCategoryEnum.SYSTEM: NotificationPriorityEnum.LOW,
}


class ReminderTypeEnum(str, enum.Enum):
    INTERVIEW_UPCOMING = "interview_upcoming"
    ASSESSMENT_DEADLINE = "assessment_deadline"
    OFFER_EXPIRY = "offer_expiry"
    RESUME_UPDATE = "resume_update"
    FOLLOW_UP = "follow_up"
    RECRUITER_REPLY = "recruiter_reply"


class ReminderStatusEnum(str, enum.Enum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"


# Smart-reminder lead times (in minutes before the target event) fired in
# sequence per the spec's "24h / 2h / 30min before an interview" example.
INTERVIEW_REMINDER_LEAD_MINUTES: tuple[int, ...] = (24 * 60, 2 * 60, 30)
ASSESSMENT_REMINDER_LEAD_MINUTES: tuple[int, ...] = (24 * 60, 2 * 60)
OFFER_EXPIRY_REMINDER_LEAD_MINUTES: tuple[int, ...] = (48 * 60, 24 * 60)


class ScheduledJobStatusEnum(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class ReportPeriodEnum(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"
