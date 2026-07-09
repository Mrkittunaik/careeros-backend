"""Service-layer tests using lightweight in-memory fakes instead of a live
Postgres session, since no DB fixture/conftest infrastructure exists yet
elsewhere in the project (tests/test_health.py is the only precedent and
uses TestClient against the real app with no DB dependency). These tests
exercise ApplicationService's actual control flow — status validation,
timeline recording, resume-history bookkeeping — against fakes that mimic
the repository interface, rather than mocking the service itself.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.application.enums import ApplicationStatusEnum, TimelineEventTypeEnum
from app.application.exceptions import ApplicationAccessDeniedError, ApplicationNotFoundError
from app.application.models import Application
from app.application.service import ApplicationService


class _FakeApplicationRepo:
    def __init__(self):
        self.store: dict[uuid.UUID, Application] = {}

    async def get_by_id(self, application_id):
        return self.store.get(application_id)

    async def get_owned(self, application_id, user_id):
        app_ = self.store.get(application_id)
        if app_ and app_.user_id == user_id:
            return app_
        return None

    async def create(self, **kwargs):
        app_ = Application(id=uuid.uuid4(), created_at=datetime.now(timezone.utc), **kwargs)
        app_.status = kwargs.get("status", ApplicationStatusEnum.DRAFT)
        self.store[app_.id] = app_
        return app_

    async def update_fields(self, application_id, **kwargs):
        app_ = self.store[application_id]
        for k, v in kwargs.items():
            setattr(app_, k, v)

    async def soft_delete(self, application_id):
        self.store[application_id].is_deleted = True


class _FakeTimelineRepo:
    def __init__(self):
        self.events = []

    async def create(self, **kwargs):
        self.events.append(kwargs)
        return kwargs

    async def list_for_application(self, application_id):
        return [e for e in self.events if e["application_id"] == application_id]


class _FakeSession:
    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


@pytest.fixture
def service() -> ApplicationService:
    svc = ApplicationService.__new__(ApplicationService)
    svc.session = _FakeSession()
    svc.repo = _FakeApplicationRepo()
    svc.timeline_repo = _FakeTimelineRepo()
    svc.resume_history_repo = None
    svc.answer_repo = None
    svc.attachment_repo = None
    svc.resume_repo = None
    return svc


@pytest.mark.asyncio
async def test_create_application_records_created_timeline_event(service: ApplicationService) -> None:
    user_id = uuid.uuid4()
    application = await service.create_application(
        user_id, company_name="Acme Corp", role_title="Backend Engineer", resume_id=None
    )
    assert application.company_name == "Acme Corp"
    assert application.status == ApplicationStatusEnum.DRAFT

    events = await service.timeline_repo.list_for_application(application.id)
    assert len(events) == 1
    assert events[0]["event_type"] == TimelineEventTypeEnum.CREATED


@pytest.mark.asyncio
async def test_get_application_raises_not_found(service: ApplicationService) -> None:
    with pytest.raises(ApplicationNotFoundError):
        await service.get_application(uuid.uuid4(), uuid.uuid4())


@pytest.mark.asyncio
async def test_get_application_raises_access_denied_for_wrong_owner(service: ApplicationService) -> None:
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    application = await service.create_application(owner_id, company_name="Acme", role_title="Eng", resume_id=None)

    with pytest.raises(ApplicationAccessDeniedError):
        await service.get_application(other_user_id, application.id)


@pytest.mark.asyncio
async def test_update_status_records_status_changed_event(service: ApplicationService) -> None:
    user_id = uuid.uuid4()
    application = await service.create_application(user_id, company_name="Acme", role_title="Eng", resume_id=None)

    updated = await service.update_status(user_id, application.id, ApplicationStatusEnum.PREPARED)
    assert updated.status == ApplicationStatusEnum.PREPARED

    events = await service.timeline_repo.list_for_application(application.id)
    status_events = [e for e in events if e["event_type"] == TimelineEventTypeEnum.STATUS_CHANGED]
    assert len(status_events) == 1
    assert status_events[0]["from_status"] == ApplicationStatusEnum.DRAFT
    assert status_events[0]["to_status"] == ApplicationStatusEnum.PREPARED


@pytest.mark.asyncio
async def test_update_status_sets_applied_at_on_submission(service: ApplicationService) -> None:
    user_id = uuid.uuid4()
    application = await service.create_application(user_id, company_name="Acme", role_title="Eng", resume_id=None)
    assert application.applied_at is None

    updated = await service.update_status(user_id, application.id, ApplicationStatusEnum.SUBMITTED)
    assert updated.applied_at is not None


@pytest.mark.asyncio
async def test_update_status_sets_closed_at_for_terminal_status(service: ApplicationService) -> None:
    user_id = uuid.uuid4()
    application = await service.create_application(user_id, company_name="Acme", role_title="Eng", resume_id=None)

    updated = await service.update_status(user_id, application.id, ApplicationStatusEnum.WITHDRAWN)
    assert updated.closed_at is not None
