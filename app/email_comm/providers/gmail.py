import base64
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.core.config import settings
from app.email_comm.exceptions import EmailProviderAuthError, EmailSyncFailedError
from app.email_comm.providers.base import EmailProviderClient, RawEmailMessage

logger = logging.getLogger("app.email_comm.providers.gmail")

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_SCOPES = "https://www.googleapis.com/auth/gmail.readonly"


async def exchange_authorization_code(*, code: str, redirect_uri: str) -> dict:
    """Exchanges an OAuth authorization code for access/refresh tokens."""
    async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            GMAIL_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        raise EmailProviderAuthError("gmail", response.text[:500])
    return response.json()


class GmailClient(EmailProviderClient):
    def __init__(self, *, access_token: str, refresh_token: str | None, email_address: str):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.email_address = email_address

    async def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def refresh_access_token(self) -> tuple[str, datetime]:
        if not self.refresh_token:
            raise EmailProviderAuthError("gmail", "No refresh token stored for this account.")
        async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                GMAIL_TOKEN_URL,
                data={
                    "refresh_token": self.refresh_token,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                },
            )
        if response.status_code != 200:
            raise EmailProviderAuthError("gmail", response.text[:500])
        payload = response.json()
        self.access_token = payload["access_token"]
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.get("expires_in", 3600))
        return self.access_token, expires_at

    async def register_webhook(self) -> dict:
        """Gmail push notifications require a Google Cloud Pub/Sub topic.
        `GMAIL_PUBSUB_TOPIC` must be configured; watch requests expire
        after 7 days and must be renewed by a scheduled task."""
        if not settings.GMAIL_PUBSUB_TOPIC:
            raise EmailSyncFailedError("GMAIL_PUBSUB_TOPIC is not configured.", stage="webhook_registration")
        async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{GMAIL_API_BASE}/watch",
                headers=await self._headers(),
                json={"topicName": settings.GMAIL_PUBSUB_TOPIC, "labelFilterAction": "include", "labelIds": ["INBOX"]},
            )
        if response.status_code != 200:
            raise EmailSyncFailedError(response.text[:500], stage="webhook_registration")
        return response.json()

    async def fetch_messages(
        self, *, since: datetime | None = None, cursor: str | None = None, limit: int = 200
    ) -> tuple[list[RawEmailMessage], str | None]:
        async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS) as client:
            if cursor:
                # Delta sync via historyId — only IDs of changed messages.
                message_ids, next_cursor = await self._list_history(client, start_history_id=cursor)
            else:
                message_ids, next_cursor = await self._list_full(client, since=since, limit=limit)

            messages: list[RawEmailMessage] = []
            for msg_id in message_ids[:limit]:
                raw = await self._get_message(client, msg_id)
                if raw:
                    messages.append(raw)
        return messages, next_cursor

    async def _list_full(self, client: httpx.AsyncClient, *, since: datetime | None, limit: int) -> tuple[list[str], str | None]:
        params: dict = {"maxResults": min(limit, 500), "q": "category:primary -in:chats"}
        if since:
            params["q"] += f" after:{int(since.timestamp())}"
        response = await client.get(f"{GMAIL_API_BASE}/messages", headers=await self._headers(), params=params)
        if response.status_code != 200:
            raise EmailSyncFailedError(response.text[:500], stage="list_messages")
        data = response.json()
        ids = [m["id"] for m in data.get("messages", [])]

        profile_resp = await client.get(f"{GMAIL_API_BASE}/profile", headers=await self._headers())
        next_cursor = None
        if profile_resp.status_code == 200:
            next_cursor = profile_resp.json().get("historyId")
        return ids, next_cursor

    async def _list_history(self, client: httpx.AsyncClient, *, start_history_id: str) -> tuple[list[str], str | None]:
        response = await client.get(
            f"{GMAIL_API_BASE}/history",
            headers=await self._headers(),
            params={"startHistoryId": start_history_id, "historyTypes": "messageAdded"},
        )
        if response.status_code != 200:
            raise EmailSyncFailedError(response.text[:500], stage="list_history")
        data = response.json()
        ids: list[str] = []
        for item in data.get("history", []):
            for added in item.get("messagesAdded", []):
                ids.append(added["message"]["id"])
        return ids, data.get("historyId", start_history_id)

    async def _get_message(self, client: httpx.AsyncClient, message_id: str) -> RawEmailMessage | None:
        response = await client.get(
            f"{GMAIL_API_BASE}/messages/{message_id}", headers=await self._headers(), params={"format": "full"}
        )
        if response.status_code != 200:
            logger.warning("gmail_fetch_message_failed", extra={"message_id": message_id, "status": response.status_code})
            return None
        payload = response.json()
        headers = {h["name"].lower(): h["value"] for h in payload.get("payload", {}).get("headers", [])}
        body_raw = _extract_body(payload.get("payload", {}))
        body_clean = _strip_html(body_raw)
        try:
            received_at = parsedate_to_datetime(headers.get("date", "")) if headers.get("date") else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            received_at = datetime.now(timezone.utc)

        return RawEmailMessage(
            message_id=payload.get("id", message_id),
            thread_id=payload.get("threadId"),
            from_email=_extract_email(headers.get("from", "")),
            from_name=_extract_name(headers.get("from", "")),
            to_email=_extract_email(headers.get("to", "")),
            subject=headers.get("subject"),
            body_raw=body_raw,
            body_clean=body_clean,
            received_at=received_at,
            is_read="UNREAD" not in payload.get("labelIds", []),
            headers=headers,
        )


def _extract_body(payload: dict) -> str:
    def walk(part: dict) -> str | None:
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime_type in ("text/plain", "text/html"):
            try:
                return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                return None
        for sub in part.get("parts", []) or []:
            found = walk(sub)
            if found:
                return found
        return None

    return walk(payload) or ""


def _strip_html(text: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_email(header_value: str) -> str:
    if "<" in header_value and ">" in header_value:
        return header_value.split("<", 1)[1].split(">", 1)[0].strip()
    return header_value.strip()


def _extract_name(header_value: str) -> str | None:
    if "<" in header_value:
        return header_value.split("<", 1)[0].strip().strip('"') or None
    return None
