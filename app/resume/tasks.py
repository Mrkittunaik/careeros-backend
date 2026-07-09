"""Resume module Celery tasks — MongoDB version.

Converted from SQLAlchemy/Postgres (old version kept as
tasks.py.postgres.bak). Background tasks run outside FastAPI's request
lifecycle, so there's no authenticated user to resolve a possible
bring-your-own-database connection through -- following the precedent
set by app.application.tasks, these always operate against the shared
default Mongo database via `get_default_mongo_db()`, never a user's own
database. (If per-user-database background processing is needed later,
the resume_id -> user_id -> own DB lookup would need to happen inside
`_run()` before constructing the repositories, same as any future task
in another module.)
"""

import asyncio
import logging

from app.core.celery_app import celery_app

logger = logging.getLogger("app.resume.tasks")


@celery_app.task(name="app.resume.tasks.run_full_resume_pipeline", bind=True, max_retries=3)
def run_full_resume_pipeline(self, resume_id: str) -> dict:
    """Full async pipeline triggered right after upload:
    parse -> structured AI extraction -> AI analysis -> ATS scoring -> embedding.
    Each stage updates Resume.status so the frontend can poll progress.
    """

    async def _run() -> dict:
        from app.core.mongo import get_default_mongo_db
        from app.resume.ai_engine import AIResumeEngine
        from app.resume.embeddings import upsert_resume_embedding
        from app.resume.exceptions import ResumeParsingFailedError
        from app.resume.models import AIProviderEnum, ResumeStatusEnum
        from app.resume.parsing import extract_raw_text
        from app.resume.repositories import ResumeAIAnalysisRepository, ResumeATSReportRepository, ResumeRepository
        from app.resume.storage import download_file

        db = get_default_mongo_db()
        repo = ResumeRepository(db)
        resume = await repo.get_by_id(resume_id)
        if not resume:
            logger.warning("resume_pipeline_resume_not_found", extra={"resume_id": resume_id})
            return {"status": "not_found"}

        try:
            await repo.set_status(resume_id, ResumeStatusEnum.PARSING)

            file_bytes = download_file(resume.storage_key)
            raw_text = extract_raw_text(file_bytes, resume.file_type)

            engine = AIResumeEngine(db, user_id=resume.user_id)
            extraction = await engine.extract_structured_data(raw_text)
            parsed = extraction["parsed"]

            await repo.update_fields(
                resume_id,
                raw_text=raw_text,
                parsed_json=parsed,
                skills_extracted=parsed.get("skills", []),
                experience_extracted=parsed.get("experience", []),
                education_extracted=parsed.get("education", []),
                projects_extracted=parsed.get("projects", []),
                certifications=parsed.get("certifications", []),
                status=ResumeStatusEnum.PARSED,
            )

            # AI analysis
            await repo.set_status(resume_id, ResumeStatusEnum.ANALYZING)

            analysis_result = await engine.analyze_resume(raw_text, parsed)
            ai_repo = ResumeAIAnalysisRepository(db)

            provider_used = analysis_result.get("provider_used") or "groq"
            await ai_repo.create(
                resume_id=resume_id,
                provider_used=AIProviderEnum(provider_used) if provider_used in AIProviderEnum._value2member_map_ else AIProviderEnum.GROQ,
                classification=analysis_result.get("classification"),
                experience_score=analysis_result.get("experience_score"),
                strengths=analysis_result.get("strengths", []),
                weaknesses=analysis_result.get("weaknesses", []),
                rewrite_suggestions=analysis_result.get("rewrite_suggestions", []),
                missing_skills=analysis_result.get("missing_skills", []),
                raw_response=analysis_result,
            )

            # ATS scoring (general, no specific JD)
            ats_result = await engine.score_ats(raw_text, parsed, job_description=None)
            ats_repo = ResumeATSReportRepository(db)
            await ats_repo.create(
                resume_id=resume_id,
                job_description_text=None,
                score=ats_result.get("overall_score", 0),
                keyword_match_score=ats_result.get("keyword_match_score"),
                skill_relevance_score=ats_result.get("skill_relevance_score"),
                experience_relevance_score=ats_result.get("experience_relevance_score"),
                format_compatibility_score=ats_result.get("format_compatibility_score"),
                readability_score=ats_result.get("readability_score"),
                missing_keywords=ats_result.get("missing_keywords", []),
                suggestions=ats_result.get("suggestions", []),
            )
            await repo.update_fields(resume_id, ats_score=ats_result.get("overall_score", 0))

            # Embedding generation
            try:
                embed_text = f"{resume.title}\n{raw_text}"
                doc_id = upsert_resume_embedding(
                    resume_id, resume.user_id, embed_text,
                    metadata={"title": resume.title, "classification": analysis_result.get("classification") or ""},
                )
                await repo.update_fields(resume_id, embedding_id=doc_id)
            except Exception:  # noqa: BLE001
                logger.exception("resume_embedding_failed_non_fatal", extra={"resume_id": resume_id})

            await repo.set_status(resume_id, ResumeStatusEnum.READY)
            return {"status": "ready", "resume_id": resume_id}

        except ResumeParsingFailedError as exc:
            await repo.set_status(resume_id, ResumeStatusEnum.FAILED, failure_reason=str(exc))
            logger.error("resume_pipeline_parsing_failed", extra={"resume_id": resume_id, "reason": str(exc)})
            return {"status": "failed", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001
            await repo.set_status(resume_id, ResumeStatusEnum.FAILED, failure_reason=str(exc))
            logger.exception("resume_pipeline_unexpected_failure", extra={"resume_id": resume_id})
            raise

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30) from exc


@celery_app.task(name="app.resume.tasks.recompute_job_matches_for_resume", bind=True, max_retries=3)
def recompute_job_matches_for_resume(self, resume_id: str, job_descriptions: list[dict]) -> dict:
    """Batch job-matching updates for a resume against a list of
    {job_id, job_description, job_role_title} dicts — e.g. triggered when a
    resume is re-parsed/optimized and existing match scores go stale.
    """

    async def _run() -> dict:
        from app.core.mongo import get_default_mongo_db
        from app.resume.ai_engine import AIResumeEngine
        from app.resume.repositories import ResumeJobMatchRepository, ResumeRepository

        db = get_default_mongo_db()
        repo = ResumeRepository(db)
        resume = await repo.get_by_id(resume_id)
        if not resume:
            return {"status": "not_found"}

        engine = AIResumeEngine(db, user_id=resume.user_id)
        match_repo = ResumeJobMatchRepository(db)
        updated = 0
        for jd in job_descriptions:
            try:
                result = await engine.match_job(
                    resume.raw_text or "", resume.parsed_json, jd["job_description"], jd.get("job_role_title")
                )
                await match_repo.create(
                    resume_id=resume_id,
                    job_id=jd.get("job_id"),
                    job_description_text=jd["job_description"],
                    job_role_title=jd.get("job_role_title"),
                    match_percentage=result.get("match_percentage", 0),
                    skill_overlap=result.get("skill_overlap", []),
                    missing_requirements=result.get("missing_requirements", []),
                    experience_fit_score=result.get("experience_fit_score"),
                    recommendation_score=result.get("recommendation_score"),
                )
                updated += 1
            except Exception:  # noqa: BLE001
                logger.exception("job_match_recompute_failed", extra={"resume_id": resume_id})
                continue
        return {"status": "completed", "updated": updated}

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30) from exc
