import asyncio
import logging
import uuid

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal

logger = logging.getLogger("app.ai_core.tasks")


@celery_app.task(name="app.ai_core.tasks.analyze_email_async", bind=True, max_retries=3)
def analyze_email_async(self, user_id: str, email_text: str, source_email_id: str | None = None) -> dict:
    """Async entrypoint for email analysis — used when emails arrive via a
    webhook/inbox-sync job rather than a direct user-initiated API call, so
    the sync path (e.g. an email provider webhook) isn't blocked on an LLM
    round-trip.
    """

    async def _run() -> dict:
        from app.ai_core.email_analysis import EmailAnalysisEngine
        from app.ai_core.exceptions import EmailAnalysisFailedError

        async with AsyncSessionLocal() as session:
            engine = EmailAnalysisEngine(session, uuid.UUID(user_id))
            try:
                result = await engine.analyze(
                    email_text, uuid.UUID(source_email_id) if source_email_id else None
                )
                await session.commit()
                return {"status": "completed", "email_analysis_id": str(result.id)}
            except EmailAnalysisFailedError as exc:
                await session.rollback()
                logger.error("email_analysis_task_failed", extra={"user_id": user_id, "reason": str(exc)})
                return {"status": "failed", "reason": str(exc)}

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30) from exc


@celery_app.task(name="app.ai_core.tasks.rank_resumes_for_job_async", bind=True, max_retries=3)
def rank_resumes_for_job_async(self, user_id: str, job_profile_id: str) -> dict:
    """Batch-ranks all of a user's resumes against a job profile — used
    right after a new job is added so match scores are ready by the time
    the user opens the job, instead of computed on first view.
    """

    async def _run() -> dict:
        from app.ai_core.matching_engine import MatchingEngine
        from app.ai_core.repositories import JobProfileRepository
        from app.resume.repositories import ResumeRepository

        async with AsyncSessionLocal() as session:
            uid = uuid.UUID(user_id)
            job_repo = JobProfileRepository(session)
            job_profile = await job_repo.get_by_id(uuid.UUID(job_profile_id))
            if not job_profile or job_profile.user_id != uid:
                return {"status": "not_found"}

            resume_repo = ResumeRepository(session)
            resumes, _ = await resume_repo.list_for_user(uid, limit=50, offset=0)

            engine = MatchingEngine(session, uid)
            results = await engine.rank_resumes(resumes, job_profile)
            await session.commit()
            return {"status": "completed", "ranked": len(results)}

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30) from exc
