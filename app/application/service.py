"""Application module service — MongoDB version.

Converted from SQLAlchemy/Postgres (old version kept as
service.py.postgres.bak). Because timeline/answers/attachments/resume
history are now embedded on the Application document itself (see
models.py), most "list_x" methods just read a field off the already-
fetched application instead of a separate repository query.

NOTE: select_resume(), generate_cover_letter(), and generate_answer()
call into app.resume / app.ai_core, which are still on the old
Postgres stack and not wired up yet. Rather than leave them silently
broken, they raise ModuleNotYetAvailableError with a clear message.
They'll be un-stubbed as soon as resume/ai_core are converted to Mongo.
"""

import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.application.constants import MAX_ATTACHMENTS_PER_APPLICATION
from app.application.enums import (
    TERMINAL_STATUSES,
    ApplicationSortFieldEnum,
    ApplicationStatusEnum,
    SortDirectionEnum,
    TimelineEventTypeEnum,
)
from app.application.events import ApplicationEvent, emit
from app.application.exceptions import (
    AnswerNotFoundError,
    ApplicationAccessDeniedError,
    ApplicationNotFoundError,
    AttachmentLimitExceededError,
    AttachmentNotFoundError,
    ResumeNotAvailableForApplicationError,
)
from app.application.models import (
    Application,
    ApplicationAnswer,
    ApplicationAttachment,
    ApplicationResumeHistory,
    ApplicationTimelineEvent,
)
from app.application.repository import ApplicationRepository
from app.application.utils import compute_package_completeness
from app.application.validators import validate_status_transition
from app.auth.repositories import UserRepository, UserProfileRepository
from app.core.exceptions import AppError

logger = logging.getLogger("app.application.service")


# --- Bot field direct-match helpers ---
# Small keyword -> profile-attribute mapping so obvious fields (name,
# email, phone, location...) get filled instantly without touching AI.

def _build_direct_match_map(user, profile) -> dict[str, str | None]:
    return {
        "email": getattr(user, "email", None),
        "phone": getattr(user, "phone", None),
        "mobile": getattr(user, "phone", None),
        "name": getattr(user, "full_name", None),
        "full name": getattr(user, "full_name", None),
        "first name": (getattr(user, "full_name", None) or "").split(" ")[0] or None,
        "last name": (getattr(user, "full_name", None) or "").split(" ")[-1] or None,
        "location": getattr(profile, "preferred_locations", None) and profile.preferred_locations[0] or None,
        "city": getattr(profile, "preferred_locations", None) and profile.preferred_locations[0] or None,
        "current title": getattr(profile, "current_title", None),
        "job title": getattr(profile, "current_title", None),
        "linkedin": getattr(profile, "linkedin_url", None),
        "github": getattr(profile, "github_url", None),
        "portfolio": getattr(profile, "portfolio_url", None),
        "website": getattr(profile, "portfolio_url", None),
        "salary": getattr(profile, "salary_expectation", None),
        "expected salary": getattr(profile, "salary_expectation", None),
        "work mode": getattr(profile, "work_mode", None),
        "years of experience": (
            str(profile.experience_years) if getattr(profile, "experience_years", None) is not None else None
        ),
        "experience": (
            str(profile.experience_years) if getattr(profile, "experience_years", None) is not None else None
        ),
    }


def _match_direct_field(field: dict, direct_match_map: dict[str, str | None]) -> str | None:
    haystack = " ".join(
        str(field.get(key) or "") for key in ("question", "name")
    ).lower()
    for keyword, value in direct_match_map.items():
        if value and keyword in haystack:
            return value
    return None


class ModuleNotYetAvailableError(AppError):
    """Raised by methods that depend on app.resume / app.ai_core, which
    have not been converted to MongoDB yet. Temporary — remove once those
    modules are live and these methods are un-stubbed.
    """

    code = "APPLICATION_090"

    def __init__(self, feature: str):
        super().__init__(
            f"'{feature}' is temporarily unavailable while the Resume/AI Core "
            "modules are being migrated to MongoDB.",
            details={"feature": feature},
        )


class ApplicationService:
    """Owns Application lifecycle and package assembly."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = ApplicationRepository(db)

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    async def create_application(self, user_id: str, **fields) -> Application:
        # resume linkage is optional at creation time; if given, we still
        # can't verify ownership against app.resume yet (not converted),
        # so we accept it as-is and just record it. This mirrors the old
        # behavior's *intent* without a hard dependency on ResumeRepository.
        application = await self.repo.create(user_id=str(user_id), **fields)

        await self._record_timeline_event(
            application,
            event_type=TimelineEventTypeEnum.CREATED,
            to_status=application.status,
            description=f"Application created for {application.role_title} at {application.company_name}.",
        )
        return await self._get_owned_or_raise(application.id, user_id)

    async def get_application(self, user_id: str, application_id: str) -> Application:
        return await self._get_owned_or_raise(application_id, user_id)

    async def update_application(self, user_id: str, application_id: str, **fields) -> Application:
        application = await self._get_owned_or_raise(application_id, user_id)
        clean_fields = {k: v for k, v in fields.items() if v is not None}
        if clean_fields:
            await self.repo.update_fields(application_id, **clean_fields)
            await self._record_timeline_event(
                application,
                event_type=TimelineEventTypeEnum.UPDATED,
                description="Application details updated.",
                metadata={"fields_changed": list(clean_fields.keys())},
            )
        return await self._get_owned_or_raise(application_id, user_id)

    async def delete_application(self, user_id: str, application_id: str) -> None:
        application = await self._get_owned_or_raise(application_id, user_id)
        await self._record_timeline_event(
            application, event_type=TimelineEventTypeEnum.DELETED, description="Application deleted."
        )
        await self.repo.soft_delete(application_id)

    async def search_applications(
        self,
        user_id: str,
        *,
        query: str | None = None,
        statuses: list[ApplicationStatusEnum] | None = None,
        priorities=None,
        company_name: str | None = None,
        min_match_score: float | None = None,
        include_terminal: bool = True,
        sort_by: ApplicationSortFieldEnum = ApplicationSortFieldEnum.UPDATED_AT,
        sort_direction: SortDirectionEnum = SortDirectionEnum.DESC,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Application], int]:
        return await self.repo.search(
            user_id,
            query=query,
            statuses=statuses,
            priorities=priorities,
            company_name=company_name,
            min_match_score=min_match_score,
            include_terminal=include_terminal,
            sort_by=sort_by,
            sort_direction=sort_direction,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Status management
    # ------------------------------------------------------------------

    async def update_status(
        self,
        user_id: str,
        application_id: str,
        new_status: ApplicationStatusEnum,
        *,
        description: str | None = None,
        strict_transition: bool = False,
    ) -> Application:
        application = await self._get_owned_or_raise(application_id, user_id)
        old_status = application.status

        validate_status_transition(old_status, new_status, strict=strict_transition)

        update_values: dict = {"status": new_status.value}
        now = datetime.now(timezone.utc)
        if new_status in (ApplicationStatusEnum.SUBMITTED, ApplicationStatusEnum.APPLIED) and not application.applied_at:
            update_values["applied_at"] = now
        if new_status in TERMINAL_STATUSES and not application.closed_at:
            update_values["closed_at"] = now

        await self.repo.update_fields(application_id, **update_values)

        await self._record_timeline_event(
            application,
            event_type=TimelineEventTypeEnum.STATUS_CHANGED,
            from_status=old_status,
            to_status=new_status,
            description=description or f"Status changed from {old_status.value} to {new_status.value}.",
        )

        application = await self._get_owned_or_raise(application_id, user_id)

        await emit(
            ApplicationEvent(
                event_type=TimelineEventTypeEnum.STATUS_CHANGED,
                application_id=application.id,
                user_id=str(user_id),
                from_status=old_status,
                to_status=new_status,
            )
        )
        return application

    async def get_timeline(self, user_id: str, application_id: str) -> list[ApplicationTimelineEvent]:
        application = await self._get_owned_or_raise(application_id, user_id)
        return application.timeline_events

    # ------------------------------------------------------------------
    # Resume selection / version history
    # ------------------------------------------------------------------

    async def select_resume(
        self,
        user_id: str,
        application_id: str,
        *,
        resume_id: str | None,
        use_ai_selection: bool,
    ) -> Application:
        # Depends on app.resume.services.ResumeService, not yet converted
        # to Mongo. Once it is, restore the original logic (see
        # service.py.postgres.bak for the exact implementation to port).
        raise ModuleNotYetAvailableError("Resume selection")

    async def get_resume_history(self, user_id: str, application_id: str) -> list[ApplicationResumeHistory]:
        application = await self._get_owned_or_raise(application_id, user_id)
        return application.resume_history

    # ------------------------------------------------------------------
    # Cover letter generation (delegates to AI Core - not yet converted)
    # ------------------------------------------------------------------

    async def generate_cover_letter(self, user_id: str, application_id: str, *, tone: str) -> Application:
        raise ModuleNotYetAvailableError("AI cover letter generation")

    # ------------------------------------------------------------------
    # AI answer generation (delegates to AI Core - not yet converted)
    # ------------------------------------------------------------------

    async def generate_answer(
        self, user_id: str, application_id: str, *, question: str, word_limit: int | None
    ) -> ApplicationAnswer:
        raise ModuleNotYetAvailableError("AI answer generation")

    async def add_manual_answer(self, user_id: str, application_id: str, *, question: str, answer: str) -> ApplicationAnswer:
        application = await self._get_owned_or_raise(application_id, user_id)
        row = ApplicationAnswer(question=question, answer=answer, is_ai_generated=False)
        await self.repo.add_answer(application_id, row)
        await self._record_timeline_event(
            application,
            event_type=TimelineEventTypeEnum.ANSWER_GENERATED,
            description="Manual answer added.",
            metadata={"answer_id": row.id},
        )
        return row

    async def list_answers(self, user_id: str, application_id: str) -> list[ApplicationAnswer]:
        application = await self._get_owned_or_raise(application_id, user_id)
        return application.answers

    async def delete_answer(self, user_id: str, application_id: str, answer_id: str) -> None:
        application = await self._get_owned_or_raise(application_id, user_id)
        if not any(a.id == answer_id for a in application.answers):
            raise AnswerNotFoundError(answer_id)
        await self.repo.delete_answer(application_id, answer_id)

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    async def add_attachment(self, user_id: str, application_id: str, **fields) -> ApplicationAttachment:
        application = await self._get_owned_or_raise(application_id, user_id)
        if len(application.attachments) >= MAX_ATTACHMENTS_PER_APPLICATION:
            raise AttachmentLimitExceededError(MAX_ATTACHMENTS_PER_APPLICATION)

        attachment = ApplicationAttachment(**fields)
        await self.repo.add_attachment(application_id, attachment)
        await self._record_timeline_event(
            application,
            event_type=TimelineEventTypeEnum.ATTACHMENT_ADDED,
            description=f"Attachment added: {fields.get('attachment_type')}.",
            metadata={"attachment_id": attachment.id},
        )
        return attachment

    async def list_attachments(self, user_id: str, application_id: str) -> list[ApplicationAttachment]:
        application = await self._get_owned_or_raise(application_id, user_id)
        return application.attachments

    async def remove_attachment(self, user_id: str, application_id: str, attachment_id: str) -> None:
        application = await self._get_owned_or_raise(application_id, user_id)
        if not any(a.id == attachment_id for a in application.attachments):
            raise AttachmentNotFoundError(attachment_id)
        await self.repo.delete_attachment(application_id, attachment_id)
        await self._record_timeline_event(
            application,
            event_type=TimelineEventTypeEnum.ATTACHMENT_REMOVED,
            description="Attachment removed.",
            metadata={"attachment_id": attachment_id},
        )

    # ------------------------------------------------------------------
    # Application package builder
    # ------------------------------------------------------------------

    async def build_package(self, user_id: str, application_id: str) -> dict:
        application = await self._get_owned_or_raise(application_id, user_id)

        # resume_data intentionally omitted for now - depends on
        # app.resume, not yet converted. is_complete/missing_items will
        # always flag "resume" as missing until that module is back.
        resume_data = None
        cover_letter_data = {"id": application.cover_letter_id} if application.cover_letter_id else None

        is_complete, missing = compute_package_completeness(
            has_resume=resume_data is not None,
            has_cover_letter=cover_letter_data is not None,
            attachment_count=len(application.attachments),
        )

        await self._record_timeline_event(
            application,
            event_type=TimelineEventTypeEnum.PACKAGE_BUILT,
            description="Application package assembled.",
            metadata={"is_complete": is_complete, "missing_items": missing},
        )

        return {
            "application": application,
            "resume": resume_data,
            "cover_letter": cover_letter_data,
            "answers": application.answers,
            "attachments": application.attachments,
            "is_complete": is_complete,
            "missing_items": missing,
        }

    # ------------------------------------------------------------------
    # Bot field-answer assist (bot-overlay)
    # ------------------------------------------------------------------

    async def get_bot_field_answers(
        self,
        user_id: str,
        *,
        job_url: str,
        job_title: str | None,
        company_name: str | None,
        fields: list[dict],
    ) -> dict:
        """Fills in as many scanned form fields as possible for the bot.

        1. Direct-match against the user's account + profile (name, email,
           phone, location, etc.) - covers most fields with zero AI cost.
        2. File-type fields get resolved against app.resume (once that
           module is Mongo-ready).
        3. Anything left over would normally go to app.ai_core in one
           batched call for full job context - see the TODO below. Until
           ai_core is converted to Mongo, those fields are simply left
           unanswered (flagged if required, silently skipped if not).
        """
        # users/user_profiles live in the shared default Mongo DB, not the
        # per-user BYO-database self.db may be pointing at.
        from app.core.mongo import get_default_mongo_db

        default_db = get_default_mongo_db()
        user = await UserRepository(default_db).get_by_id(user_id)
        profile = await UserProfileRepository(default_db).get_by_user_id(user_id)

        direct_match_map = _build_direct_match_map(user, profile)

        answers: dict[str, str] = {}
        unanswered_required: list[int] = []
        needs_ai: list[dict] = []
        resume_file_id: str | None = None
        resume_file_name: str | None = None
        resume_download_url: str | None = None

        for field in fields:
            index = field["index"]
            tag = (field.get("tag") or "").lower()
            field_type = (field.get("type") or "").lower()

            if tag == "input" and field_type == "file":
                # Resolved separately below, once per request (not per-field).
                continue

            value = _match_direct_field(field, direct_match_map)
            if value is not None:
                answers[str(index)] = value
                continue

            needs_ai.append(field)

        # --- File fields: resolve via app.resume (not yet Mongo-ready) ---
        file_fields = [f for f in fields if (f.get("tag") or "").lower() == "input" and (f.get("type") or "").lower() == "file"]
        if file_fields:
            try:
                # Depends on app.resume.services.ResumeService, not yet
                # converted to Mongo. Once it is, pick the best-matching
                # resume for this job and populate the three fields below.
                raise ModuleNotYetAvailableError("Resume auto-selection for bot")
            except ModuleNotYetAvailableError:
                for f in file_fields:
                    if f.get("required"):
                        unanswered_required.append(f["index"])

        # --- Remaining open-ended fields: batch to ai_core (not yet ready) ---
        # TODO: wire real AI call here once ai_core is on Mongo. When ready,
        # send job_title/company_name/job_url + the full `needs_ai` question
        # list together in a single ai_core call so the model has complete
        # job context and we only pay for one API round-trip, then merge
        # the parsed { index: answer } pairs into `answers` below.
        for f in needs_ai:
            if f.get("required"):
                unanswered_required.append(f["index"])
            # optional fields: left out of `answers` entirely, bot skips silently

        return {
            "answers": answers,
            "resume_file_id": resume_file_id,
            "resume_file_name": resume_file_name,
            "resume_download_url": resume_download_url,
            "unanswered_required": unanswered_required,
        }

    # ------------------------------------------------------------------
    # Job agent integration
    # ------------------------------------------------------------------

    async def create_from_agent(
        self,
        user_id: str,
        *,
        company_name: str,
        role_title: str,
        job_url: str | None,
        job_description_text: str | None,
        source_site_url: str,
        hr_email: str | None,
    ) -> Application:
        """Called once the local Playwright job agent (see /job_agent)
        applies to a job on the user's behalf. Creates the Application
        already in APPLIED status with source='agent' so the dashboard
        can distinguish bot-submitted applications from manual ones.
        """
        return await self.repo.create_from_agent(
            user_id=str(user_id),
            company_name=company_name,
            role_title=role_title,
            job_url=job_url,
            job_description_text=job_description_text,
            source_site_url=source_site_url,
            hr_email=hr_email,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_owned_or_raise(self, application_id: str, user_id: str) -> Application:
        application = await self.repo.get_by_id(application_id)
        if not application:
            raise ApplicationNotFoundError(str(application_id))
        if application.user_id != str(user_id):
            raise ApplicationAccessDeniedError()
        return application

    async def _record_timeline_event(
        self,
        application: Application,
        *,
        event_type: TimelineEventTypeEnum,
        from_status: ApplicationStatusEnum | None = None,
        to_status: ApplicationStatusEnum | None = None,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        event = ApplicationTimelineEvent(
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            description=description,
            event_metadata=metadata or {},
            actor_user_id=application.user_id,
        )
        await self.repo.add_timeline_event(application.id, event)
