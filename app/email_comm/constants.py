MAX_BODY_CLEAN_CHARS_FOR_AI = 6000
MAX_EMAILS_PER_SYNC_BATCH = 200
DEFAULT_HISTORICAL_IMPORT_DAYS = 90
CLASSIFICATION_MIN_CONFIDENCE_TO_AUTOAPPLY_STATUS = 60.0

# Keyword pre-filter used before spending an AI call, per the spec's Email
# Filtering Rules. Not exhaustive — a coarse, cheap first pass only; the AI
# classifier is the source of truth for `is_job_related`.
JOB_RELATED_KEYWORDS: tuple[str, ...] = (
    "application", "applied", "interview", "recruiter", "recruiting",
    "hiring", "candidate", "position", "role", "offer letter",
    "assessment", "coding challenge", "onboarding", "shortlisted",
    "hr team", "talent acquisition", "next steps", "resume", "cv",
)

EXCLUDE_SENDER_DOMAIN_KEYWORDS: tuple[str, ...] = (
    "noreply-newsletter", "marketing", "promo", "unsubscribe-only",
)

NEWSLETTER_HEADER_HINTS: tuple[str, ...] = ("list-unsubscribe", "precedence: bulk")

INTERVIEW_MEETING_LINK_DOMAINS: dict[str, str] = {
    "zoom.us": "zoom",
    "meet.google.com": "google_meet",
    "teams.microsoft.com": "microsoft_teams",
}
