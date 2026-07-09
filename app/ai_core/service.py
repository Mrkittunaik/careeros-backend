import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.cold_email import ColdEmailEngine
from app.ai_core.cover_letter import CoverLetterEngine
from app.ai_core.email_analysis import EmailAnalysisEngine
from app.ai_core.exceptions import JobProfileAccessDeniedError, JobProfileNotFoundError
from app.ai_core.job_intelligence import JobIntelligenceEngine
from app.ai_core.matching_engine import MatchingEngine
from app.ai_core.models import ColdEmailGeneration, CoverLetterGeneration, EmailAnalysisResult, JobProfile, ResumeMatchResult
from app.ai_core.repositories import AICallLogRepository, JobProfileRepository
from app.resume.exceptions import ResumeAccessDeniedError, ResumeNotFoundError
from app.resume.repositories import ResumeRepository


class AICoreService:
    """Facade over the AI Core engines. Owns cross-module access-control
    checks (resume ownership, job profile ownership) so router handlers
    stay thin, mirroring app.resume.services.ResumeService's role.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_profile_repo = JobProfileRepository(session)
        self.resume_repo = ResumeRepository(session)
        self.call_log_repo = AICallLogRepository(session)

    async def _get_owned_resume(self, user_id: uuid.UUID, resume_id: uuid.UUID):
        resume = await self.resume_repo.get_by_id(resume_id)
        if not resume:
            raise ResumeNotFoundError(str(resume_id))
        if resume.user_id != user_id:
            raise ResumeAccessDeniedError()
        return resume

    async def _get_owned_job_profile(self, user_id: uuid.UUID, job_profile_id: uuid.UUID) -> JobProfile:
        profile = await self.job_profile_repo.get_by_id(job_profile_id)
        if not profile:
            raise JobProfileNotFoundError(str(job_profile_id))
        if profile.user_id != user_id:
            raise JobProfileAccessDeniedError()
        return profile

    # --- Job Intelligence ---

    async def analyze_job(self, user_id: uuid.UUID, job_description: str, source_job_id: uuid.UUID | None) -> JobProfile:
        engine = JobIntelligenceEngine(self.session, user_id)
        profile = await engine.analyze_and_store(job_description, source_job_id)
        await self.session.commit()
        return profile

    async def get_job_profile(self, user_id: uuid.UUID, job_profile_id: uuid.UUID) -> JobProfile:
        return await self._get_owned_job_profile(user_id, job_profile_id)

    async def list_job_profiles(self, user_id: uuid.UUID, limit: int, offset: int) -> list[JobProfile]:
        return await self.job_profile_repo.list_for_user(user_id, limit, offset)

    # --- Matching ---

    async def match_single(self, user_id: uuid.UUID, resume_id: uuid.UUID, job_profile_id: uuid.UUID) -> ResumeMatchResult:
        resume = await self._get_owned_resume(user_id, resume_id)
        job_profile = await self._get_owned_job_profile(user_id, job_profile_id)
        engine = MatchingEngine(self.session, user_id)
        result = await engine.match(resume, job_profile)
        await self.session.commit()
        return result

    async def rank_resumes(
        self, user_id: uuid.UUID, job_profile_id: uuid.UUID, resume_ids: list[uuid.UUID] | None
    ) -> list[ResumeMatchResult]:
        job_profile = await self._get_owned_job_profile(user_id, job_profile_id)
        if resume_ids:
            resumes = [await self._get_owned_resume(user_id, rid) for rid in resume_ids]
        else:
            resumes, _ = await self.resume_repo.list_for_user(user_id, limit=50, offset=0)  # type: ignore[misc]

        engine = MatchingEngine(self.session, user_id)
        results = await engine.rank_resumes(resumes, job_profile)
        await self.session.commit()
        return results

    # --- Cover letter ---

    async def generate_cover_letter(
        self,
        user_id: uuid.UUID,
        resume_id: uuid.UUID,
        company_name: str,
        role_title: str,
        job_description: str | None,
        tone: str,
        job_profile_id: uuid.UUID | None,
    ) -> CoverLetterGeneration:
        resume = await self._get_owned_resume(user_id, resume_id)
        if job_profile_id:
            await self._get_owned_job_profile(user_id, job_profile_id)
        engine = CoverLetterEngine(self.session, user_id)
        letter = await engine.generate(
            resume=resume,
            company_name=company_name,
            role_title=role_title,
            job_description=job_description,
            tone=tone,
            job_profile_id=job_profile_id,
        )
        await self.session.commit()
        return letter

    # --- Cold email ---

    async def generate_cold_email(
        self,
        user_id: uuid.UUID,
        resume_id: uuid.UUID,
        role_title: str,
        company_name: str,
        recruiter_name: str | None,
        recruiter_title: str | None,
        job_profile_id: uuid.UUID | None,
    ) -> ColdEmailGeneration:
        resume = await self._get_owned_resume(user_id, resume_id)
        if job_profile_id:
            await self._get_owned_job_profile(user_id, job_profile_id)
        engine = ColdEmailEngine(self.session, user_id)
        email = await engine.generate(
            resume=resume,
            role_title=role_title,
            company_name=company_name,
            recruiter_name=recruiter_name,
            recruiter_title=recruiter_title,
            job_profile_id=job_profile_id,
        )
        await self.session.commit()
        return email

    # --- Email analysis ---

    async def analyze_email(
        self, user_id: uuid.UUID, email_text: str, source_email_id: uuid.UUID | None
    ) -> EmailAnalysisResult:
        engine = EmailAnalysisEngine(self.session, user_id)
        result = await engine.analyze(email_text, source_email_id)
        await self.session.commit()
        return result

    # --- Usage analytics ---

    async def usage_summary(self, user_id: uuid.UUID) -> dict:
        return await self.call_log_repo.usage_summary(user_id)
