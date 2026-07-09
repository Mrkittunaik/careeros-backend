import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.models import (
    AICallLog,
    ColdEmailGeneration,
    CoverLetterGeneration,
    EmailAnalysisResult,
    JobProfile,
    ResumeMatchResult,
)


class JobProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> JobProfile:
        obj = JobProfile(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_by_id(self, job_profile_id: uuid.UUID) -> JobProfile | None:
        stmt = select(JobProfile).where(JobProfile.id == job_profile_id, JobProfile.is_deleted.is_(False))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[JobProfile]:
        stmt = (
            select(JobProfile)
            .where(JobProfile.user_id == user_id, JobProfile.is_deleted.is_(False))
            .order_by(JobProfile.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class ResumeMatchResultRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> ResumeMatchResult:
        obj = ResumeMatchResult(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_for_job_profile(self, job_profile_id: uuid.UUID) -> list[ResumeMatchResult]:
        stmt = (
            select(ResumeMatchResult)
            .where(ResumeMatchResult.job_profile_id == job_profile_id, ResumeMatchResult.is_deleted.is_(False))
            .order_by(ResumeMatchResult.match_score.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


class CoverLetterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> CoverLetterGeneration:
        obj = CoverLetterGeneration(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_by_id(self, letter_id: uuid.UUID) -> CoverLetterGeneration | None:
        stmt = select(CoverLetterGeneration).where(
            CoverLetterGeneration.id == letter_id, CoverLetterGeneration.is_deleted.is_(False)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ColdEmailRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> ColdEmailGeneration:
        obj = ColdEmailGeneration(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj


class EmailAnalysisRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> EmailAnalysisResult:
        obj = EmailAnalysisResult(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[EmailAnalysisResult]:
        stmt = (
            select(EmailAnalysisResult)
            .where(EmailAnalysisResult.user_id == user_id, EmailAnalysisResult.is_deleted.is_(False))
            .order_by(EmailAnalysisResult.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class AICallLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def usage_summary(self, user_id: uuid.UUID) -> dict:
        stmt = select(AICallLog).where(AICallLog.user_id == user_id, AICallLog.is_deleted.is_(False))
        logs = list((await self.session.execute(stmt)).scalars().all())
        total = len(logs)
        successes = sum(1 for l in logs if l.success)
        by_provider: dict[str, int] = {}
        for l in logs:
            if l.provider_used:
                by_provider[l.provider_used] = by_provider.get(l.provider_used, 0) + 1
        return {
            "total_calls": total,
            "success_rate": round(successes / total, 4) if total else None,
            "cache_hit_rate": round(sum(1 for l in logs if l.cache_hit) / total, 4) if total else None,
            "provider_distribution": by_provider,
        }
