import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import settings
from app.email_comm.exceptions import EmailProviderAuthError, EmailSyncFailedError
from app.email_comm.providers.base import EmailProviderClient, RawEmailMessage

logger = logging.getLogger("app.email_comm.providers.outlook")

OUTLOOK_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0/me"
OUTLOOK_SCOPES = "offline_access Mail.Read"


async def exchange_authorization_code(*, code: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            OUTLOOK_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.OUTLOOK_CLIENT_ID,
                "client_secret": settings.OUTLOOK_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": OUTLOOK_SCOPES,
            },
        )
    if response.status_code != 200:
        raise EmailProviderAuthError("outlook", response.text[:500])
    return response.json()


class OutlookClient(EmailProviderClient):
    def __init__(self, *, access_token: str, refresh_token: str | None, email_address: str):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.email_address = email_address

    async def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def refresh_access_token(self) -> tuple[str, datetime]:
        if not self.refresh_token:
            raise EmailProviderAuthError("outlook", "No refresh token stored for this account.")
        async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                OUTLOOK_TOKEN_URL,
                data={
                    "refresh_token": self.refresh_token,
                    "client_id": settings.OUTLOOK_CLIENT_ID,
                    "client_secret": settings.OUTLOOK_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "scope": OUTLOOK_SCOPES,
                },
            )
        if response.status_code != 200:
            raise EmailProviderAuthError("outlook", response.text[:500])
        payload = response.json()
        self.access_token = payload["access_token"]
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.get("expires_in", 3600))
        return self.access_token, expires_at

    async def register_webhook(self) -> dict:
        if not settings.OUTLOOK_WEBHOOK_NOTIFICATION_URL:
            raise EmailSyncFailedError("OUTLOOK_WEBHOOK_NOTIFICATION_URL is not configured.", stage="webhook_registration")
        expiration = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.0Z")
        async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://graph.microsoft.com/v1.0/subscriptions",
                headers=await self._headers(),
                json={
                    "changeType": "created",
                    "notificationUrl": settings.OUTLOOK_WEBHOOK_NOTIFICATION_URL,
                    "resource": "me/mailFolders('Inbox')/messages",
                    "expirationDateTime": expiration,
                    "clientState": settings.OUTLOOK_WEBHOOK_CLIENT_STATE or "careeros",
                },
            )
        if response.status_code not in (200, 201):
            raise EmailSyncFailedError(response.text[:500], stage="webhook_registration")
        return response.json()

    async def fetch_messages(
        self, *, since: datetime | None = None, cursor: str | None = None, limit: int = 200
    ) -> tuple[list[RawEmailMessage], str | None]:
        async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS) as client:
            url = cursor or f"{GRAPH_API_BASE}/mailFolders/Inbox/messages/delta"
            params = None
            if not cursor:
                params = {"$top": min(limit, 100)}
                if since:
                    params["$filter"] = f"receivedDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"

            messages: list[RawEmailMessage] = []
            next_link = None
            page = 0
            while url and page < (limit // 100 + 1):
                response = await client.get(url, headers=await self._headers(), params=params)
                params = None  # only applies to first request
                if response.status_code != 200:
                    raise EmailSyncFailedError(response.text[:500], stage="list_messages")
                data = response.json()
                for item in data.get("value", []):
                    messages.append(_to_raw_message(item))
                url = data.get("@odata.nextLink")
                next_link = data.get("@odata.deltaLink", next_link)
                page += 1
                if len(messages) >= limit:
                    break

        return messages[:limit], next_link


def _to_raw_message(item: dict) -> RawEmailMessage:
    body = item.get("body", {})
    body_raw = body.get("content", "") or ""
    body_clean = _strip_html(body_raw) if body.get("contentType") == "html" else body_raw
    from_field = item.get("from", {}).get("emailAddress", {})
    to_recipients = item.get("toRecipients", [])
    to_email = to_recipients[0]["emailAddress"]["address"] if to_recipients else None
    received_raw = item.get("receivedDateTime")
    try:
        received_at = datetime.fromisoformat(received_raw.replace("Z", "+00:00")) if received_raw else datetime.now(timezone.utc)
    except ValueError:
        received_at = datetime.now(timezone.utc)

    return RawEmailMessage(
        message_id=item.get("id", ""),
        thread_id=item.get("conversationId"),
        from_email=from_field.get("address", ""),
        from_name=from_field.get("name"),
        to_email=to_email,
        subject=item.get("subject"),
        body_raw=body_raw,
        body_clean=body_clean,
        received_at=received_at,
        is_read=bool(item.get("isRead", False)),
        headers={},
    )


def _strip_html(text: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
