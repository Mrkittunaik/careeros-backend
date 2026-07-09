import hashlib

from app.email_comm.constants import EXCLUDE_SENDER_DOMAIN_KEYWORDS, JOB_RELATED_KEYWORDS
from app.email_comm.enums import EmailFolderCategoryEnum
from app.email_comm.providers.base import RawEmailMessage


def body_hash(subject: str | None, body_clean: str, from_email: str) -> str:
    """Stable hash used for duplicate detection (Duplicate Detection
    Rules section) alongside message_id/thread_id checks."""
    payload = f"{from_email.lower()}|{(subject or '').strip().lower()}|{body_clean.strip().lower()[:2000]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def classify_folder_category(message: RawEmailMessage) -> EmailFolderCategoryEnum:
    """Cheap keyword pre-filter run before the AI classifier, per the
    spec's Email Filtering Rules. This never marks something job-related on
    its own — it only screens out obvious noise so we don't burn an AI call
    on newsletters/promotions/spam.
    """
    sender = (message.from_email or "").lower()
    subject = (message.subject or "").lower()
    body = (message.body_clean or "").lower()
    list_unsub = "list-unsubscribe" in {k.lower() for k in message.headers.keys()}

    if any(kw in sender for kw in EXCLUDE_SENDER_DOMAIN_KEYWORDS):
        return EmailFolderCategoryEnum.PROMOTION
    if list_unsub and not any(kw in subject or kw in body for kw in JOB_RELATED_KEYWORDS):
        return EmailFolderCategoryEnum.NEWSLETTER

    haystack = f"{subject} {body}"
    if any(kw in haystack for kw in JOB_RELATED_KEYWORDS):
        return EmailFolderCategoryEnum.JOB_RELATED

    return EmailFolderCategoryEnum.UNRELATED


def should_run_ai_classification(category: EmailFolderCategoryEnum) -> bool:
    """Only spend an AI call on emails that survive the coarse filter —
    saves cost per the Email Filtering Rules / cost-efficiency intent."""
    return category == EmailFolderCategoryEnum.JOB_RELATED
