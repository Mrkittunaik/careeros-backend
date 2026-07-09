import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.exceptions import CoverLetterGenerationFailedError
from app.ai_core.models import CoverLetterGeneration
from app.ai_core.orchestrator import AIRouter
from app.ai_core.repositories import CoverLetterRepository

logger = logging.getLogger("app.ai_core.cover_letter")

_VALID_TONES = {"professional", "enthusiastic", "formal", "conversational", "confident"}


class CoverLetterEngine:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self.router = AIRouter(session, user_id=user_id)
        self.repo = CoverLetterRepository(session)

    async def generate(
        self,
        *,
        resume,
        company_name: str,
        role_title: str,
        job_description: str | None = None,
        tone: str = "professional",
        job_profile_id: uuid.UUID | None = None,
    ) -> CoverLetterGeneration:
        tone = tone if tone in _VALID_TONES else "professional"
        try:
            result = await self.router.dispatch_json(
                stage="cover_letter",
                prompt_key="cover_letter_prompt",
                prompt_variables={
                    "resume_parsed_json": {
                        "skills": resume.skills_extracted,
                        "experience": resume.experience_extracted,
                        "projects": resume.projects_extracted,
                        "certifications": resume.certifications,
                    },
                    "company_name": company_name,
                    "role_title": role_title,
                    "job_description": (job_description or "")[:4000],
                    "tone": tone,
                },
                use_cache=False,  # generative/creative output shouldn't be deduped across requests
            )
        except Exception as exc:  # noqa: BLE001
            raise CoverLetterGenerationFailedError(str(exc)) from exc

        content = result.get("cover_letter")
        if not content or not isinstance(content, str):
            raise CoverLetterGenerationFailedError("AI response missing 'cover_letter' text.")

        return await self.repo.create(
            user_id=self.user_id,
            resume_id=resume.id,
            job_profile_id=job_profile_id,
            company_name=company_name,
            role_title=role_title,
            tone=tone,
            content=content,
            provider_used=result.get("_provider_used"),
        )
