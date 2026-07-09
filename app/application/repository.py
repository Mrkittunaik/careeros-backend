"""Application module repository — MongoDB (Motor) version.

Converted from SQLAlchemy/Postgres (old version kept as
repository.py.postgres.bak). Because timeline/answers/attachments/resume
history are now embedded sub-documents on Application (see models.py),
what used to be five separate repository classes collapses into one:
appending an event/answer/attachment is a `$push` on the parent
document instead of an insert into a child table.
"""

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.application.enums import (
    TERMINAL_STATUSES,
    ApplicationPriorityEnum,
    ApplicationSortFieldEnum,
    ApplicationStatusEnum,
    SortDirectionEnum,
    TimelineEventTypeEnum,
)
from app.application.models import (
    Application,
    ApplicationAnswer,
    ApplicationAttachment,
    ApplicationResumeHistory,
    ApplicationTimelineEvent,
)
from app.core.mongo_base import utcnow

_SORT_FIELD_MAP = {
    ApplicationSortFieldEnum.CREATED_AT: "created_at",
    ApplicationSortFieldEnum.UPDATED_AT: "updated_at",
    ApplicationSortFieldEnum.STATUS: "status",
    ApplicationSortFieldEnum.PRIORITY: "priority",
    ApplicationSortFieldEnum.MATCH_SCORE: "ai_match_score",
    ApplicationSortFieldEnum.COMPANY_NAME: "company_name",
    ApplicationSortFieldEnum.APPLIED_AT: "applied_at",
}


class ApplicationRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["applications"]

    async def get_by_id(self, application_id: str) -> Application | None:
        doc = await self.col.find_one({"_id": str(application_id), "is_deleted": False})
        return Application.from_mongo(doc)

    async def get_owned(self, application_id: str, user_id: str) -> Application | None:
        doc = await self.col.find_one(
            {"_id": str(application_id), "user_id": str(user_id), "is_deleted": False}
        )
        return Application.from_mongo(doc)

    async def create(self, **kwargs) -> Application:
        application = Application(**kwargs)
        await self.col.insert_one(application.to_mongo())
        return application

    async def update_fields(self, application_id: str, **kwargs) -> None:
        kwargs["updated_at"] = utcnow()
        await self.col.update_one({"_id": str(application_id)}, {"$set": kwargs})

    async def set_status(
        self,
        application_id: str,
        status: ApplicationStatusEnum,
        *,
        applied_at: datetime | None = None,
        closed_at: datetime | None = None,
    ) -> None:
        values: dict = {"status": status.value, "updated_at": utcnow()}
        if applied_at is not None:
            values["applied_at"] = applied_at
        if closed_at is not None:
            values["closed_at"] = closed_at
        await self.col.update_one({"_id": str(application_id)}, {"$set": values})

    async def soft_delete(self, application_id: str) -> None:
        await self.col.update_one(
            {"_id": str(application_id)},
            {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc)}},
        )

    async def search(
        self,
        user_id: str,
        *,
        query: str | None = None,
        statuses: list[ApplicationStatusEnum] | None = None,
        priorities: list[ApplicationPriorityEnum] | None = None,
        company_name: str | None = None,
        min_match_score: float | None = None,
        include_terminal: bool = True,
        sort_by: ApplicationSortFieldEnum = ApplicationSortFieldEnum.UPDATED_AT,
        sort_direction: SortDirectionEnum = SortDirectionEnum.DESC,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Application], int]:
        filt: dict = {"user_id": str(user_id), "is_deleted": False}

        if query:
            filt["$or"] = [
                {"company_name": {"$regex": query, "$options": "i"}},
                {"role_title": {"$regex": query, "$options": "i"}},
            ]
        if statuses:
            filt["status"] = {"$in": [s.value for s in statuses]}
        if priorities:
            filt["priority"] = {"$in": [p.value for p in priorities]}
        if company_name:
            filt["company_name"] = {"$regex": company_name, "$options": "i"}
        if min_match_score is not None:
            filt["ai_match_score"] = {"$gte": min_match_score}
        if not include_terminal:
            existing = filt.get("status")
            if isinstance(existing, dict):
                existing["$nin"] = [s.value for s in TERMINAL_STATUSES]
            else:
                filt["status"] = {"$nin": [s.value for s in TERMINAL_STATUSES]}

        total = await self.col.count_documents(filt)

        sort_field = _SORT_FIELD_MAP[sort_by]
        direction = 1 if sort_direction == SortDirectionEnum.ASC else -1

        cursor = self.col.find(filt).sort(sort_field, direction).skip(offset).limit(limit)
        rows = [Application.from_mongo(doc) async for doc in cursor]
        return rows, total

    async def count_for_user(self, user_id: str) -> int:
        return await self.col.count_documents({"user_id": str(user_id), "is_deleted": False})

    # --- Embedded sub-document operations ---
    # These replace the old ApplicationTimelineRepository /
    # ApplicationAnswerRepository / ApplicationAttachmentRepository /
    # ApplicationResumeHistoryRepository classes. Each pushes onto the
    # parent Application document rather than inserting into a child table.

    async def add_timeline_event(self, application_id: str, event: ApplicationTimelineEvent) -> None:
        await self.col.update_one(
            {"_id": str(application_id)},
            {"$push": {"timeline_events": event.model_dump(mode="json")}, "$set": {"updated_at": utcnow()}},
        )

    async def add_resume_history(self, application_id: str, history: ApplicationResumeHistory) -> None:
        if history.was_active:
            # Deactivate any prior "active" history entries first, so
            # `was_active` always reflects a single current selection -
            # same invariant the old repository enforced.
            await self.col.update_one(
                {"_id": str(application_id)},
                {"$set": {"resume_history.$[elem].was_active": False}},
                array_filters=[{"elem.was_active": True}],
            )
        await self.col.update_one(
            {"_id": str(application_id)},
            {"$push": {"resume_history": history.model_dump(mode="json")}, "$set": {"updated_at": utcnow()}},
        )

    async def add_answer(self, application_id: str, answer: ApplicationAnswer) -> None:
        await self.col.update_one(
            {"_id": str(application_id)},
            {"$push": {"answers": answer.model_dump(mode="json")}, "$set": {"updated_at": utcnow()}},
        )

    async def delete_answer(self, application_id: str, answer_id: str) -> None:
        await self.col.update_one(
            {"_id": str(application_id)},
            {"$pull": {"answers": {"id": answer_id}}, "$set": {"updated_at": utcnow()}},
        )

    async def add_attachment(self, application_id: str, attachment: ApplicationAttachment) -> None:
        await self.col.update_one(
            {"_id": str(application_id)},
            {"$push": {"attachments": attachment.model_dump(mode="json")}, "$set": {"updated_at": utcnow()}},
        )

    async def delete_attachment(self, application_id: str, attachment_id: str) -> None:
        await self.col.update_one(
            {"_id": str(application_id)},
            {"$pull": {"attachments": {"id": attachment_id}}, "$set": {"updated_at": utcnow()}},
        )

    # --- Agent-specific writes ---
    # Used by the local Playwright job agent (see /job_agent) once it
    # authenticates: creates an application record straight from a scan
    # result rather than the manual dashboard flow.

    async def create_from_agent(
        self,
        *,
        user_id: str,
        company_name: str,
        role_title: str,
        job_url: str | None,
        job_description_text: str | None,
        source_site_url: str,
        hr_email: str | None,
    ) -> Application:
        application = Application(
            user_id=str(user_id),
            company_name=company_name,
            role_title=role_title,
            job_url=job_url,
            job_description_text=job_description_text,
            status=ApplicationStatusEnum.APPLIED,
            source="agent",
            source_site_url=source_site_url,
            hr_email=hr_email,
            applied_at=datetime.now(timezone.utc),
        )
        application.timeline_events.append(
            ApplicationTimelineEvent(
                event_type=TimelineEventTypeEnum.CREATED,
                to_status=ApplicationStatusEnum.APPLIED,
                description="Application created by the CareerOS job agent.",
            )
        )
        await self.col.insert_one(application.to_mongo())
        return application
