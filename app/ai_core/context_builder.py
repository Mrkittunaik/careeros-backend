"""Context Builder — assembles the minimal, relevant, token-optimized
context sent to the AI Router for any given request, per the master
prompt's Context Builder System.

Sources pulled in (only those that exist yet in this codebase are wired
live; downstream modules — job platform data, application history, email
history — are stubbed with clear TODO hooks so this builder doesn't need
rework when those modules land):

- User profile (auth module)                -> live
- Resume data (resume module)                -> live
- Job description (caller-supplied)          -> live
- AI memory (ai_core.memory)                 -> live
- Past applications                          -> TODO: app.application module
- Email history                              -> TODO: app.email_comm module
- Skill database                             -> derived from resume skills for now
- Previous AI responses                      -> AICallLog / AIMemoryEntry
- Job platform data                          -> TODO: app.job module

Context is always: cleaned (no HTML/markdown noise), token-optimized
(truncated to safe limits), structured (dict, not free text), and
relevant-only (caller declares which sources it needs).
"""

import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.memory import AIMemoryManager
from app.auth.models import User

logger = logging.getLogger("app.ai_core.context_builder")

# Conservative per-field character caps to keep prompts token-efficient.
_MAX_RESUME_TEXT_CHARS = 8000
_MAX_JOB_DESC_CHARS = 6000
_MAX_MEMORY_ITEMS = 5


def clean_text(raw: str | None) -> str:
    """Strips HTML tags, collapses whitespace, and removes non-printable
    noise so downstream prompts aren't padded with formatting junk.
    """
    if not raw:
        return ""
    no_html = re.sub(r"<[^>]+>", " ", raw)
    collapsed = re.sub(r"\s+", " ", no_html).strip()
    return collapsed


class ContextBuilder:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.memory = AIMemoryManager(session)

    async def build_user_profile_context(self, user: User) -> dict:
        return {
            "full_name": user.full_name,
            "email": user.email,
            "profile_completed": user.profile_completed,
        }

    async def build_resume_context(self, resume) -> dict:
        """`resume` is an app.resume.models.Resume instance. Kept loosely
        typed to avoid a hard import-time coupling between modules.
        """
        return {
            "title": resume.title,
            "skills": resume.skills_extracted[:50],
            "experience": resume.experience_extracted[:10],
            "education": resume.education_extracted[:5],
            "projects": resume.projects_extracted[:10],
            "certifications": resume.certifications[:10],
            "raw_text": clean_text(resume.raw_text)[:_MAX_RESUME_TEXT_CHARS],
        }

    def build_job_description_context(self, job_description: str) -> str:
        return clean_text(job_description)[:_MAX_JOB_DESC_CHARS]

    async def build_memory_context(self, user_id: uuid.UUID, memory_type: str | None = None) -> list[dict]:
        entries = await self.memory.recent(user_id, memory_type=memory_type, limit=_MAX_MEMORY_ITEMS)
        return [{"summary": e.summary, "outcome": e.outcome} for e in entries]

    def build_skill_database_context(self, resumes: list) -> list[str]:
        """Derives a deduplicated skill set across all of a user's resumes
        as a lightweight stand-in for a dedicated skill taxonomy service.
        """
        skills: set[str] = set()
        for r in resumes:
            for s in getattr(r, "skills_extracted", []) or []:
                if isinstance(s, str):
                    skills.add(s.strip())
        return sorted(skills)[:100]

    async def build_full_context(
        self,
        *,
        user: User,
        job_description: str | None = None,
        resume=None,
        include_memory: bool = True,
    ) -> dict:
        """Convenience aggregator for stages that want "everything relevant"
        in one call (e.g. cover letter / cold email generation).
        """
        context: dict = {"user_profile": await self.build_user_profile_context(user)}

        if resume is not None:
            context["resume"] = await self.build_resume_context(resume)

        if job_description:
            context["job_description"] = self.build_job_description_context(job_description)

        if include_memory:
            context["memory"] = await self.build_memory_context(user.id)

        # TODO(future modules): once app.application / app.email_comm / app.job
        # land, wire in:
        #   context["past_applications"] = await self._build_application_history(user.id)
        #   context["email_history"] = await self._build_email_history(user.id)
        #   context["job_platform_data"] = await self._build_job_platform_data(...)

        return context
