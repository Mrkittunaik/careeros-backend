from fastapi import APIRouter, Depends, Query, Request, status

from app.auth.dependencies import get_current_active_user
from app.auth.models import User
from app.email_comm.dependencies import get_email_account_service, get_email_ingestion_service, get_email_query_service
from app.email_comm.enums import EmailClassificationEnum, EmailFolderCategoryEnum, SyncTriggerEnum
from app.email_comm.schemas import (
    EmailAccountResponse,
    EmailDetailResponse,
    EmailListItemResponse,
    EmailManualLinkRequest,
    EmailSyncJobResponse,
    GmailConnectRequest,
    ImapConnectRequest,
    OutlookConnectRequest,
    SyncTriggerRequest,
    WebhookGmailNotification,
)
from app.email_comm.service import EmailAccountService, EmailIngestionService, EmailQueryService
from app.email_comm.tasks import handle_gmail_webhook, handle_outlook_webhook, sync_account

router = APIRouter(prefix="/email", tags=["Email Intelligence"])


# --- Account connection ---

@router.post("/accounts/gmail", response_model=EmailAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_gmail(
    payload: GmailConnectRequest,
    user: User = Depends(get_current_active_user),
    service: EmailAccountService = Depends(get_email_account_service),
):
    account = await service.connect_gmail(
        user.id, authorization_code=payload.authorization_code, redirect_uri=payload.redirect_uri
    )
    sync_account.delay(str(account.id), trigger=SyncTriggerEnum.INITIAL_IMPORT.value)
    return account


@router.post("/accounts/outlook", response_model=EmailAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_outlook(
    payload: OutlookConnectRequest,
    user: User = Depends(get_current_active_user),
    service: EmailAccountService = Depends(get_email_account_service),
):
    account = await service.connect_outlook(
        user.id, authorization_code=payload.authorization_code, redirect_uri=payload.redirect_uri
    )
    sync_account.delay(str(account.id), trigger=SyncTriggerEnum.INITIAL_IMPORT.value)
    return account


@router.post("/accounts/imap", response_model=EmailAccountResponse, status_code=status.HTTP_201_CREATED)
async def connect_imap(
    payload: ImapConnectRequest,
    user: User = Depends(get_current_active_user),
    service: EmailAccountService = Depends(get_email_account_service),
):
    account = await service.connect_imap(
        user.id,
        email_address=payload.email_address,
        password=payload.password,
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        imap_use_ssl=payload.imap_use_ssl,
    )
    sync_account.delay(str(account.id), trigger=SyncTriggerEnum.INITIAL_IMPORT.value)
    return account


@router.get("/accounts", response_model=list[EmailAccountResponse])
async def list_accounts(
    user: User = Depends(get_current_active_user), service: EmailAccountService = Depends(get_email_account_service)
):
    return await service.list_accounts(user.id)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_account(
    account_id: str,
    user: User = Depends(get_current_active_user),
    service: EmailAccountService = Depends(get_email_account_service),
):
    await service.disconnect(user.id, account_id)


# --- Sync ---

@router.post("/accounts/{account_id}/sync", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    account_id: str,
    payload: SyncTriggerRequest = SyncTriggerRequest(),
    user: User = Depends(get_current_active_user),
    account_service: EmailAccountService = Depends(get_email_account_service),
):
    # Ownership check before queueing.
    await account_service._get_owned_or_raise(account_id, user.id)  # noqa: SLF001 — internal ownership guard
    task = sync_account.delay(str(account_id), trigger=payload.trigger.value, historical_days=payload.historical_days)
    return {"status": "queued", "task_id": task.id}


@router.get("/accounts/{account_id}/sync-jobs", response_model=list[EmailSyncJobResponse])
async def list_sync_jobs(
    account_id: str,
    user: User = Depends(get_current_active_user),
    account_service: EmailAccountService = Depends(get_email_account_service),
    query_service: EmailQueryService = Depends(get_email_query_service),
):
    await account_service._get_owned_or_raise(account_id, user.id)  # noqa: SLF001 — internal ownership guard
    return await query_service.list_sync_jobs(user.id, account_id)


# --- Emails ---

@router.get("", response_model=dict)
async def list_emails(
    is_job_related: bool | None = None,
    classification: EmailClassificationEnum | None = None,
    account_id: str | None = None,
    linked_application_id: str | None = None,
    folder_category: EmailFolderCategoryEnum | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: User = Depends(get_current_active_user),
    service: EmailQueryService = Depends(get_email_query_service),
):
    emails, total = await service.list_emails(
        user.id,
        is_job_related=is_job_related,
        classification=classification,
        account_id=account_id,
        linked_application_id=linked_application_id,
        folder_category=folder_category,
        search=search,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [EmailListItemResponse.model_validate(e) for e in emails],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{email_id}", response_model=EmailDetailResponse)
async def get_email(
    email_id: str,
    user: User = Depends(get_current_active_user),
    service: EmailQueryService = Depends(get_email_query_service),
):
    return await service.get_email(user.id, email_id)


@router.post("/{email_id}/link", response_model=EmailDetailResponse)
async def link_email_to_application(
    email_id: str,
    payload: EmailManualLinkRequest,
    user: User = Depends(get_current_active_user),
    service: EmailQueryService = Depends(get_email_query_service),
):
    return await service.manual_link(user.id, email_id, payload.application_id)


# --- Webhooks (unauthenticated by user session; verified per-provider) ---

@router.post("/webhooks/gmail", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def gmail_webhook(request: Request):
    """Gmail Pub/Sub push endpoint. Verifies the request came from Google
    Pub/Sub (bearer OIDC token) before dispatching — signature/token
    verification is delegated to the reverse proxy / Pub/Sub push auth
    configuration in production, per docker/nginx/nginx.conf.
    """
    import base64
    import json

    body = await request.json()
    message = body.get("message", {})
    data = message.get("data")
    if not data:
        return
    decoded = json.loads(base64.b64decode(data).decode("utf-8"))
    notification = WebhookGmailNotification(email_address=decoded["emailAddress"], history_id=str(decoded["historyId"]))
    handle_gmail_webhook.delay(notification.email_address, notification.history_id)


@router.post("/webhooks/outlook", status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
async def outlook_webhook(request: Request, validationToken: str | None = None):  # noqa: N803 — Graph subscription handshake param name
    """Microsoft Graph change-notification endpoint. Handles the initial
    subscription validation handshake, then dispatches change notifications
    to the sync task.
    """
    if validationToken:
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(content=validationToken, status_code=200)

    body = await request.json()
    for item in body.get("value", []):
        handle_outlook_webhook.delay(item.get("subscriptionId", ""))
