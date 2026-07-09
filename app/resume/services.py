"""Resume module service layer — MongoDB version.

Converted from SQLAlchemy/Postgres (old version kept as
services.py.postgres.bak). All business logic, validation rules, and
exception behavior are identical to the Postgres version. The only
changes: `self.session` (AsyncSession) -> `self.db` (Motor database
handle), no more explicit `.commit()` calls (each repository method
writes immediately), and id parameters/returns are plain `str` instead
of `uuid.UUID` (ids are still UUID-format strings under the hood, same
convention as app.application and app.autoapply).
"""

import logging
import uuid

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.security import decrypt_secret, encrypt_secret
from app.resume.ai_engine import AIResumeEngine
from app.resume.embeddings import delete_resume_embedding, semantic_search, upsert_resume_embedding
from app.resume.exceptions import (
    FileTooLargeError,
    InvalidFileTypeError,
    InvalidSelectionRuleError,
    NoResumesAvailableError,
    ResumeAccessDeniedError,
    ResumeNotFoundError,
)
from app.resume.models import (
    AIProviderEnum,
    Resume,
    ResumeFileTypeEnum,
    ResumeStatusEnum,
)
from app.resume.parsing import extract_raw_text
from app.resume.repositories import (
    ResumeAIAnalysisRepository,
    ResumeATSReportRepository,
    ResumeJobMatchRepository,
    ResumeRepository,
    ResumeSelectionLogRepository,
    ResumeSelectionRuleRepository,
    UserAIProviderKeyRepository,
)
from app.resume.storage import build_storage_key, delete_file, get_presigned_url, upload_file
from app.resume.tasks import run_full_resume_pipeline

logger = logging.getLogger("app.resume.services")

_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # overridden by settings at call site


class ResumeService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.repo = ResumeRepository(db)
        self.ai_repo = ResumeAIAnalysisRepository(db)
        self.ats_repo = ResumeATSReportRepository(db)
        self.match_repo = ResumeJobMatchRepository(db)
        self.rule_repo = ResumeSelectionRuleRepository(db)
        self.log_repo = ResumeSelectionLogRepository(db)
        self.key_repo = UserAIProviderKeyRepository(db)

    # ------------------------------------------------------------------
    # Upload flow
    # ------------------------------------------------------------------
    async def upload_resume(
        self,
        user_id: str,
        filename: str,
        file_bytes: bytes,
        title: str | None,
        tags: list[str] | None,
    ) -> Resume:
        from app.core.config import settings

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("pdf", "docx"):
            raise InvalidFileTypeError(filename)
        max_bytes = settings.RESUME_MAX_FILE_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise FileTooLargeError(settings.RESUME_MAX_FILE_SIZE_MB)

        file_type = ResumeFileTypeEnum.PDF if ext == "pdf" else ResumeFileTypeEnum.DOCX
        resume_id = str(uuid.uuid4())
        storage_key = build_storage_key(user_id, resume_id, filename)

        content_type = "application/pdf" if file_type == ResumeFileTypeEnum.PDF else (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        upload_file(storage_key, file_bytes, content_type)
        file_url = get_presigned_url(storage_key, expires_minutes=60 * 24 * 7)

        resume = await self.repo.create(
            id=resume_id,
            user_id=str(user_id),
            title=title or filename,
            file_url=file_url,
            file_type=file_type,
            file_size_bytes=len(file_bytes),
            storage_key=storage_key,
            status=ResumeStatusEnum.UPLOADED,
            version_number=1,
            tags=tags or [],
        )

        # Trigger async background pipeline: parse -> AI analyze -> ATS score -> embed
        run_full_resume_pipeline.delay(str(resume.id))

        return resume

    async def clone_resume(self, user_id: str, resume_id: str, new_title: str | None) -> Resume:
        original = await self._get_owned_or_raise(resume_id, user_id)
        next_version = await self.repo.next_version_number(resume_id)
        root_id = original.parent_resume_id or original.id

        clone = await self.repo.create(
            user_id=str(user_id),
            title=new_title or f"{original.title} v{next_version}",
            file_url=original.file_url,
            file_type=original.file_type,
            file_size_bytes=original.file_size_bytes,
            storage_key=original.storage_key,
            raw_text=original.raw_text,
            parsed_json=original.parsed_json,
            skills_extracted=original.skills_extracted,
            experience_extracted=original.experience_extracted,
            education_extracted=original.education_extracted,
            projects_extracted=original.projects_extracted,
            certifications=original.certifications,
            status=ResumeStatusEnum.READY if original.status == ResumeStatusEnum.READY else ResumeStatusEnum.UPLOADED,
            version_number=next_version,
            parent_resume_id=root_id,
            tags=list(original.tags),
        )
        return clone

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    async def get_resume(self, user_id: str, resume_id: str) -> Resume:
        return await self._get_owned_or_raise(resume_id, user_id)

    async def list_resumes(
        self, user_id: str, *, tags: list[str] | None, status: ResumeStatusEnum | None, limit: int, offset: int
    ) -> tuple[list[Resume], int]:
        return await self.repo.list_for_user(user_id, tags=tags, status=status, limit=limit, offset=offset)

    async def update_resume(self, user_id: str, resume_id: str, **fields) -> Resume:
        await self._get_owned_or_raise(resume_id, user_id)
        clean_fields = {k: v for k, v in fields.items() if v is not None}
        if clean_fields:
            await self.repo.update_fields(resume_id, **clean_fields)
        return await self._get_owned_or_raise(resume_id, user_id)

    async def delete_resume(self, user_id: str, resume_id: str) -> None:
        resume = await self._get_owned_or_raise(resume_id, user_id)
        await self.repo.soft_delete(resume_id)
        delete_file(resume.storage_key)
        if resume.embedding_id:
            delete_resume_embedding(resume_id)

    async def get_version_chain(self, user_id: str, resume_id: str) -> list[Resume]:
        await self._get_owned_or_raise(resume_id, user_id)
        return await self.repo.get_version_chain(resume_id)

    async def _get_owned_or_raise(self, resume_id: str, user_id: str) -> Resume:
        resume = await self.repo.get_owned(resume_id, user_id)
        if not resume:
            exists = await self.repo.get_by_id(resume_id)
            if exists:
                raise ResumeAccessDeniedError()
            raise ResumeNotFoundError(str(resume_id))
        return resume

    # ------------------------------------------------------------------
    # Parsing (synchronous entry point — also used by background task)
    # ------------------------------------------------------------------
    async def parse_resume(self, user_id: str, resume_id: str) -> Resume:
        from app.resume.storage import download_file

        resume = await self._get_owned_or_raise(resume_id, user_id)
        await self.repo.set_status(resume_id, ResumeStatusEnum.PARSING)

        file_bytes = download_file(resume.storage_key)
        raw_text = extract_raw_text(file_bytes, resume.file_type)

        engine = AIResumeEngine(self.db, user_id=user_id)
        extraction = await engine.extract_structured_data(raw_text)
        parsed = extraction["parsed"]

        await self.repo.update_fields(
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
        return await self._get_owned_or_raise(resume_id, user_id)

    # ------------------------------------------------------------------
    # ATS scoring
    # ------------------------------------------------------------------
    async def score_ats(self, user_id: str, resume_id: str, job_description: str | None):
        resume = await self._get_owned_or_raise(resume_id, user_id)
        engine = AIResumeEngine(self.db, user_id=user_id)
        result = await engine.score_ats(resume.raw_text or "", resume.parsed_json, job_description)

        report = await self.ats_repo.create(
            resume_id=resume_id,
            job_description_text=job_description,
            score=result.get("overall_score", 0),
            keyword_match_score=result.get("keyword_match_score"),
            skill_relevance_score=result.get("skill_relevance_score"),
            experience_relevance_score=result.get("experience_relevance_score"),
            format_compatibility_score=result.get("format_compatibility_score"),
            readability_score=result.get("readability_score"),
            missing_keywords=result.get("missing_keywords", []),
            suggestions=result.get("suggestions", []),
        )
        await self.repo.update_fields(resume_id, ats_score=report.score)
        return report

    # ------------------------------------------------------------------
    # Job matching
    # ------------------------------------------------------------------
    async def match_job(self, user_id: str, resume_id: str, job_description: str, job_role_title: str | None, job_id: str | None):
        resume = await self._get_owned_or_raise(resume_id, user_id)
        engine = AIResumeEngine(self.db, user_id=user_id)
        result = await engine.match_job(resume.raw_text or "", resume.parsed_json, job_description, job_role_title)

        match = await self.match_repo.create(
            resume_id=resume_id,
            job_id=str(job_id) if job_id else None,
            job_description_text=job_description,
            job_role_title=job_role_title,
            match_percentage=result.get("match_percentage", 0),
            skill_overlap=result.get("skill_overlap", []),
            missing_requirements=result.get("missing_requirements", []),
            experience_fit_score=result.get("experience_fit_score"),
            recommendation_score=result.get("recommendation_score"),
        )
        return match

    # ------------------------------------------------------------------
    # Resume Selection Engine (the critical decision system)
    # ------------------------------------------------------------------
    async def select_resume_for_job(
        self, user_id: str, job_role_title: str, job_description: str | None
    ) -> dict:
        # Step 1: check user-defined rules first (highest priority wins)
        rules = await self.rule_repo.list_for_user(user_id, active_only=True)
        for rule in rules:
            if rule.job_role_pattern.lower() in job_role_title.lower():
                resume = await self.repo.get_owned(rule.resume_id, user_id)
                if resume and not resume.is_deleted:
                    await self.log_repo.create(
                        user_id=user_id,
                        resume_id=resume.id,
                        job_role_title=job_role_title,
                        selection_method="rule",
                        match_percentage=None,
                    )
                    return {
                        "selected_resume_id": resume.id,
                        "selection_method": "rule",
                        "match_percentage": None,
                        "reasoning": f"Matched user-defined rule: '{rule.job_role_pattern}'",
                        "ranked_alternatives": [],
                    }

        # Step 2: no rule matched -> AI decides by ranking all ready resumes
        resumes, _ = await self.repo.list_for_user(
            user_id, tags=None, status=ResumeStatusEnum.READY, limit=50, offset=0
        )
        if not resumes:
            raise NoResumesAvailableError()

        engine = AIResumeEngine(self.db, user_id=user_id)
        ranked = []
        for resume in resumes:
            jd = job_description or job_role_title
            try:
                match_result = await engine.match_job(resume.raw_text or "", resume.parsed_json, jd, job_role_title)
            except Exception:  # noqa: BLE001
                logger.warning("selection_match_failed_for_resume", extra={"resume_id": str(resume.id)})
                continue
            success_rate = await self.log_repo.success_rate_for_resume(resume.id)
            composite_score = (
                match_result.get("match_percentage", 0) * 0.5
                + (resume.ats_score or 0) * 0.3
                + (success_rate or 50) * 0.2
            )
            ranked.append({
                "resume_id": str(resume.id),
                "title": resume.title,
                "match_percentage": match_result.get("match_percentage", 0),
                "ats_score": resume.ats_score,
                "past_success_rate": success_rate,
                "composite_score": round(composite_score, 2),
            })

        if not ranked:
            raise NoResumesAvailableError()

        ranked.sort(key=lambda r: r["composite_score"], reverse=True)
        best = ranked[0]

        await self.log_repo.create(
            user_id=user_id,
            resume_id=best["resume_id"],
            job_role_title=job_role_title,
            selection_method="ai",
            match_percentage=best["match_percentage"],
        )

        return {
            "selected_resume_id": best["resume_id"],
            "selection_method": "ai",
            "match_percentage": best["match_percentage"],
            "reasoning": (
                f"AI-ranked best fit by skill match ({best['match_percentage']}%), "
                f"ATS score ({resume.ats_score or 'n/a'}), and past success rate."
            ),
            "ranked_alternatives": ranked[1:6],
        }

    # ------------------------------------------------------------------
    # Selection rules CRUD
    # ------------------------------------------------------------------
    async def create_selection_rule(self, user_id: str, job_role_pattern: str, resume_id: str, priority: int):
        resume = await self.repo.get_owned(resume_id, user_id)
        if not resume:
            raise InvalidSelectionRuleError("resume_id does not belong to this user or does not exist.")
        rule = await self.rule_repo.create(
            user_id=user_id, job_role_pattern=job_role_pattern, resume_id=resume_id, priority=priority
        )
        return rule

    async def list_selection_rules(self, user_id: str):
        return await self.rule_repo.list_for_user(user_id, active_only=False)

    async def delete_selection_rule(self, user_id: str, rule_id: str) -> None:
        rule = await self.rule_repo.get_owned(rule_id, user_id)
        if not rule:
            raise InvalidSelectionRuleError("Rule not found or not owned by this user.")
        await self.rule_repo.delete(rule_id)

    # ------------------------------------------------------------------
    # Optimization
    # ------------------------------------------------------------------
    async def optimize_resume(self, user_id: str, resume_id: str, target_job_description: str | None) -> dict:
        resume = await self._get_owned_or_raise(resume_id, user_id)
        engine = AIResumeEngine(self.db, user_id=user_id)
        result = await engine.optimize_resume(resume.raw_text or "", resume.parsed_json, target_job_description)
        return result

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    async def search_resumes(
        self,
        user_id: str,
        *,
        query: str | None,
        skill: str | None,
        job_role: str | None,
        min_ats_score: float | None,
        semantic: bool,
        limit: int,
    ) -> list[dict]:
        if semantic and query:
            hits = semantic_search(query, user_id, top_k=limit)
            results = []
            for hit in hits:
                resume = await self.repo.get_owned(hit["resume_id"], user_id)
                if resume:
                    results.append({
                        "resume_id": resume.id,
                        "title": resume.title,
                        "ats_score": resume.ats_score,
                        "similarity_score": hit["similarity_score"],
                        "tags": resume.tags,
                    })
            return results

        tags = [skill] if skill else None
        resumes, _ = await self.repo.list_for_user(user_id, tags=tags, status=None, limit=limit, offset=0)

        results = []
        for resume in resumes:
            if min_ats_score is not None and (resume.ats_score or 0) < min_ats_score:
                continue
            if job_role and job_role.lower() not in (resume.title or "").lower():
                skills_match = any(job_role.lower() in s.lower() for s in resume.skills_extracted if isinstance(s, str))
                if not skills_match:
                    continue
            if query and query.lower() not in (resume.title or "").lower():
                text_match = query.lower() in (resume.raw_text or "").lower()
                if not text_match:
                    continue
            results.append({
                "resume_id": resume.id,
                "title": resume.title,
                "ats_score": resume.ats_score,
                "similarity_score": None,
                "tags": resume.tags,
            })
        return results

    # ------------------------------------------------------------------
    # BYOK AI provider keys
    # ------------------------------------------------------------------
    async def set_ai_provider_key(self, user_id: str, provider: AIProviderEnum, api_key: str):
        encrypted = encrypt_secret(api_key)
        key_row = await self.key_repo.upsert(user_id, provider, encrypted)
        return key_row

    async def list_ai_provider_keys(self, user_id: str):
        return await self.key_repo.list_for_user(user_id)

    async def delete_ai_provider_key(self, user_id: str, provider: AIProviderEnum) -> bool:
        deleted = await self.key_repo.delete(user_id, provider)
        return deleted
