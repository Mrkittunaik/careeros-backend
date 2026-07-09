import email
import logging
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

from imapclient import IMAPClient

from app.email_comm.exceptions import ImapConnectionError
from app.email_comm.providers.base import EmailProviderClient, RawEmailMessage

logger = logging.getLogger("app.email_comm.providers.imap")


class ImapClientWrapper(EmailProviderClient):
    """Generic IMAP client. Runs synchronous imapclient calls — callers
    (Celery tasks) already execute outside the async event loop, so no
    thread offloading is required here."""

    def __init__(self, *, host: str, port: int, use_ssl: bool, email_address: str, password: str):
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.email_address = email_address
        self.password = password

    async def refresh_access_token(self) -> tuple[str, datetime]:
        # IMAP uses static credentials — nothing to refresh.
        return self.password, datetime.now(timezone.utc)

    async def register_webhook(self) -> dict:
        raise NotImplementedError("IMAP has no native webhook support; use IDLE polling or scheduled sync instead.")

    async def fetch_messages(
        self, *, since: datetime | None = None, cursor: str | None = None, limit: int = 200
    ) -> tuple[list[RawEmailMessage], str | None]:
        try:
            with IMAPClient(self.host, port=self.port, ssl=self.use_ssl, timeout=30) as client:
                client.login(self.email_address, self.password)
                client.select_folder("INBOX", readonly=True)

                criteria = ["SINCE", since.date()] if since else ["ALL"]
                uids = client.search(criteria)
                start_uid = int(cursor) if cursor else 0
                uids = sorted(uid for uid in uids if uid > start_uid)[:limit]

                messages: list[RawEmailMessage] = []
                if uids:
                    fetched = client.fetch(uids, ["RFC822", "FLAGS"])
                    for uid, data in fetched.items():
                        raw = _parse_rfc822(data.get(b"RFC822", b""), flags=data.get(b"FLAGS", ()))
                        if raw:
                            messages.append(raw)

                next_cursor = str(max(uids)) if uids else cursor
                return messages, next_cursor
        except Exception as exc:  # noqa: BLE001
            raise ImapConnectionError(str(exc)) from exc


def _parse_rfc822(raw_bytes: bytes, *, flags: tuple) -> RawEmailMessage | None:
    if not raw_bytes:
        return None
    msg = email.message_from_bytes(raw_bytes)

    subject = _decode_header_value(msg.get("Subject"))
    from_name, from_email = parseaddr(msg.get("From", ""))
    _, to_email = parseaddr(msg.get("To", ""))

    body_raw = ""
    body_clean = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and not body_clean:
                body_clean = _decode_payload(part)
            elif content_type == "text/html" and not body_raw:
                body_raw = _decode_payload(part)
    else:
        payload = _decode_payload(msg)
        body_raw = payload
        body_clean = payload

    if not body_clean and body_raw:
        import re

        body_clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body_raw)).strip()

    try:
        received_at = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        received_at = datetime.now(timezone.utc)

    return RawEmailMessage(
        message_id=msg.get("Message-ID", "").strip() or f"imap-{hash(raw_bytes)}",
        thread_id=msg.get("References", "").split()[0] if msg.get("References") else msg.get("In-Reply-To"),
        from_email=from_email,
        from_name=from_name or None,
        to_email=to_email or None,
        subject=subject,
        body_raw=body_raw,
        body_clean=body_clean,
        received_at=received_at,
        is_read=b"\\Seen" in flags,
        headers={k.lower(): v for k, v in msg.items()},
    )


def _decode_header_value(value: str | None) -> str | None:
    if not value:
        return None
    parts = decode_header(value)
    decoded = "".join(
        chunk.decode(enc or "utf-8", errors="ignore") if isinstance(chunk, bytes) else chunk for chunk, enc in parts
    )
    return decoded


def _decode_payload(part) -> str:
    try:
        payload = part.get_payload(decode=True)
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="ignore") if payload else ""
    except Exception:  # noqa: BLE001
        return ""
