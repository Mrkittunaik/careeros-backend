import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.exceptions import ColdEmailGenerationFailedError
from app.ai_core.models import ColdEmailGeneration
from app.ai_core.orchestrator import AIRouter
from app.ai_core.repositories import ColdEmailRepository

logger = logging.getLogger("app.ai_core.cold_email")


class ColdEmailEngine:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self.router = AIRouter(session, user_id=user_id)
        self.repo = ColdEmailRepository(session)

    async def generate(
        self,
        *,
        resume,
        role_title: str,
        company_name: str,
        recruiter_name: str | None = None,
        recruiter_title: str | None = None,
        job_profile_id: uuid.UUID | None = None,
    ) -> ColdEmailGeneration:
        recruiter_info = (
            f"{recruiter_name}, {recruiter_title}" if recruiter_name and recruiter_title
            else recruiter_name or "not available — address generically"
        )
        resume_summary = ", ".join((resume.skills_extracted or [])[:15]) or "not available"

        try:
            result = await self.router.dispatch_json(
                stage="cold_email",
                prompt_key="cold_email_prompt",
                prompt_variables={
                    "role_title": role_title,
                    "company_name": company_name,
                    "recruiter_info": recruiter_info,
                    "resume_summary": resume_summary,
                },
                use_cache=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise ColdEmailGenerationFailedError(str(exc)) from exc

        subject = result.get("subject")
        body = result.get("body")
        if not subject or not body:
            raise ColdEmailGenerationFailedError("AI response missing subject/body.")

        return await self.repo.create(
            user_id=self.user_id,
            job_profile_id=job_profile_id,
            recruiter_name=recruiter_name,
            company_name=company_name,
            role_title=role_title,
            subject=subject,
            body=body,
            follow_up_body=result.get("follow_up_body"),
            provider_used=result.get("_provider_used"),
        )
