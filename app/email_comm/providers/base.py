from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawEmailMessage:
    """Provider-normalized representation of a single inbound email, before
    any AI classification is applied."""

    message_id: str
    thread_id: str | None
    from_email: str
    from_name: str | None
    to_email: str | None
    subject: str | None
    body_raw: str
    body_clean: str
    received_at: datetime
    is_read: bool = False
    headers: dict = field(default_factory=dict)


class EmailProviderClient(ABC):
    """Common interface implemented by Gmail / Outlook / IMAP clients, per
    the spec's multi-provider Email Ingestion Flow."""

    @abstractmethod
    async def fetch_messages(
        self, *, since: datetime | None = None, cursor: str | None = None, limit: int = 200
    ) -> tuple[list[RawEmailMessage], str | None]:
        """Returns (messages, next_cursor). `cursor` is provider-specific
        (Gmail historyId, Outlook delta link, IMAP UID)."""
        raise NotImplementedError

    @abstractmethod
    async def refresh_access_token(self) -> tuple[str, datetime]:
        """Returns (new_access_token, expires_at). Only meaningful for OAuth
        providers (Gmail/Outlook); IMAP implementations may no-op."""
        raise NotImplementedError

    @abstractmethod
    async def register_webhook(self) -> dict:
        """Registers push notifications (Gmail Pub/Sub watch, Outlook Graph
        subscription). Returns provider metadata to persist. IMAP has no
        native push support and should raise NotImplementedError."""
        raise NotImplementedError
