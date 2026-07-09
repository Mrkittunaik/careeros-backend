"""Tool Execution Layer — the set of validated actions the AI Router/agent
flows may invoke, per the master prompt's Tool Execution Layer section.

Every tool call is validated against a registry (name + expected args)
before execution; unknown tools or malformed args raise
InvalidToolCallError rather than silently no-op-ing. Tools backed by
modules that don't exist yet in this codebase (job, application,
automation, notification) are registered now with a clear "not yet wired"
result so the AI Router's tool-call contract is stable and callers get a
structured response instead of an AttributeError once those modules land.
"""

import logging
import uuid
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.exceptions import InvalidToolCallError

logger = logging.getLogger("app.ai_core.tools")

ToolFunc = Callable[..., Awaitable[dict]]


class ToolExecutor:
    """Registers and dispatches tool calls. New tools are added via
    `self.register(name, func, required_args)` — keeps the registry
    declarative and easy to extend as new modules land.
    """

    def __init__(self, session: AsyncSession, user_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self._registry: dict[str, tuple[ToolFunc, set[str]]] = {}
        self._register_defaults()

    def register(self, name: str, func: ToolFunc, required_args: set[str]) -> None:
        self._registry[name] = (func, required_args)

    async def execute(self, tool_name: str, args: dict[str, Any] | None = None) -> dict:
        args = args or {}
        if tool_name not in self._registry:
            raise InvalidToolCallError(tool_name, "unknown tool")

        func, required_args = self._registry[tool_name]
        missing = required_args - set(args.keys())
        if missing:
            raise InvalidToolCallError(tool_name, f"missing required args: {sorted(missing)}")

        try:
            return await func(**args)
        except InvalidToolCallError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("tool_execution_failed", extra={"tool": tool_name})
            return {"status": "error", "tool": tool_name, "message": str(exc)}

    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        self.register("fetch_resume", self._fetch_resume, {"resume_id"})
        self.register("fetch_job_data", self._fetch_job_data, {"job_profile_id"})
        self.register("fetch_email", self._fetch_email, set())
        self.register("update_application_status", self._update_application_status, {"application_id", "status"})
        self.register("trigger_notification", self._trigger_notification, {"message"})
        self.register("start_automation", self._start_automation, {"automation_type"})

    async def _fetch_resume(self, resume_id: str) -> dict:
        from app.resume.repositories import ResumeRepository

        repo = ResumeRepository(self.session)
        resume = await repo.get_by_id(uuid.UUID(resume_id))
        if not resume or resume.user_id != self.user_id:
            return {"status": "not_found", "resume_id": resume_id}
        return {
            "status": "ok",
            "resume_id": resume_id,
            "title": resume.title,
            "skills": resume.skills_extracted,
            "ats_score": resume.ats_score,
        }

    async def _fetch_job_data(self, job_profile_id: str) -> dict:
        from app.ai_core.repositories import JobProfileRepository

        repo = JobProfileRepository(self.session)
        profile = await repo.get_by_id(uuid.UUID(job_profile_id))
        if not profile or profile.user_id != self.user_id:
            return {"status": "not_found", "job_profile_id": job_profile_id}
        return {
            "status": "ok",
            "title": profile.title,
            "company": profile.company,
            "required_skills": profile.required_skills,
        }

    async def _fetch_email(self, email_id: str | None = None) -> dict:
        # TODO: wire to app.email_comm once that module exists.
        return {"status": "not_wired", "message": "Email module not yet available."}

    async def _update_application_status(self, application_id: str, status: str) -> dict:
        # TODO: wire to app.application once that module exists.
        return {"status": "not_wired", "message": "Application module not yet available.", "requested_status": status}

    async def _trigger_notification(self, message: str) -> dict:
        # TODO: wire to a notification service/queue once that module exists.
        logger.info("notification_requested_stub", extra={"user_id": str(self.user_id), "message": message})
        return {"status": "not_wired", "message": "Notification service not yet available."}

    async def _start_automation(self, automation_type: str) -> dict:
        # TODO: wire to app.automation once that module exists.
        return {"status": "not_wired", "message": "Automation module not yet available.", "automation_type": automation_type}
