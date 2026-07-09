"""Job Intelligence Engine — analyzes raw job postings into a structured
Job Profile, per the master prompt's Job Intelligence Engine section.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.context_builder import clean_text
from app.ai_core.exceptions import JobIntelligenceFailedError
from app.ai_core.models import JobProfile, JobTypeEnum
from app.ai_core.orchestrator import AIRouter
from app.ai_core.repositories import JobProfileRepository

logger = logging.getLogger("app.ai_core.job_intelligence")

_VALID_JOB_TYPES = {t.value for t in JobTypeEnum}


class JobIntelligenceEngine:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self.router = AIRouter(session, user_id=user_id)
        self.repo = JobProfileRepository(session)

    async def analyze_and_store(self, job_description: str, source_job_id: uuid.UUID | None = None) -> JobProfile:
        cleaned = clean_text(job_description)
        try:
            result = await self.router.dispatch_json(
                stage="job_intelligence",
                prompt_key="job_description_understanding_prompt",
                prompt_variables={"job_description": cleaned[:6000]},
            )
        except Exception as exc:  # noqa: BLE001
            raise JobIntelligenceFailedError(str(exc)) from exc

        job_type_raw = str(result.get("job_type") or "unknown").lower()
        job_type = JobTypeEnum(job_type_raw) if job_type_raw in _VALID_JOB_TYPES else JobTypeEnum.UNKNOWN

        profile = await self.repo.create(
            user_id=self.user_id,
            source_job_id=source_job_id,
            raw_description=job_description,
            title=result.get("title"),
            company=result.get("company"),
            required_skills=result.get("required_skills", []),
            preferred_skills=result.get("preferred_skills", []),
            experience_level=result.get("experience_level"),
            salary_range=result.get("salary_range", {}),
            job_type=job_type,
            responsibilities=result.get("responsibilities", []),
            ats_keywords=result.get("ats_keywords", []),
            hidden_requirements=result.get("hidden_requirements", []),
            provider_used=result.get("_provider_used"),
            raw_ai_response=result,
        )
        return profile
