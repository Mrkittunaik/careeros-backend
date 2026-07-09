"""Resume-Job Matching Engine — combines semantic (embedding) similarity,
keyword overlap, and an AI reasoning pass into one weighted score, per the
master prompt's Resume-Job Matching Engine rules: "Use semantic matching
(embeddings). Use keyword overlap. Use AI reasoning layer. Combine weighted
scoring."

Weights: 30% semantic similarity, 30% keyword overlap, 40% AI reasoning —
AI reasoning gets the most weight since it can account for context (e.g.
transferable skills) that pure keyword/embedding signals miss.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.exceptions import ResumeMatchingFailedError
from app.ai_core.models import ResumeMatchResult
from app.ai_core.orchestrator import AIRouter
from app.ai_core.repositories import ResumeMatchResultRepository

logger = logging.getLogger("app.ai_core.matching_engine")

_WEIGHT_SEMANTIC = 0.3
_WEIGHT_KEYWORD = 0.3
_WEIGHT_AI_REASONING = 0.4


def _keyword_overlap_pct(resume_skills: list[str], required_skills: list[str], preferred_skills: list[str]) -> float:
    all_job_keywords = {s.strip().lower() for s in (required_skills + preferred_skills) if isinstance(s, str)}
    if not all_job_keywords:
        return 0.0
    resume_keywords = {s.strip().lower() for s in resume_skills if isinstance(s, str)}
    overlap = all_job_keywords & resume_keywords
    return round(100 * len(overlap) / len(all_job_keywords), 2)


class MatchingEngine:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self.router = AIRouter(session, user_id=user_id)
        self.repo = ResumeMatchResultRepository(session)

    async def _semantic_similarity(self, resume_id: uuid.UUID, job_description: str) -> float | None:
        try:
            from app.resume.embeddings import semantic_search

            results = semantic_search(job_description, self.user_id, top_k=25)
            for r in results:
                if r["resume_id"] == str(resume_id) and r["similarity_score"] is not None:
                    return round(max(0.0, min(1.0, r["similarity_score"])) * 100, 2)
            return None
        except Exception:  # noqa: BLE001
            logger.warning("semantic_similarity_unavailable", extra={"resume_id": str(resume_id)})
            return None

    async def match(self, resume, job_profile) -> ResumeMatchResult:
        """`resume` is an app.resume.models.Resume; `job_profile` an
        app.ai_core.models.JobProfile. Loosely typed to avoid tight
        cross-module coupling.
        """
        keyword_pct = _keyword_overlap_pct(
            resume.skills_extracted or [], job_profile.required_skills or [], job_profile.preferred_skills or []
        )
        semantic_pct = await self._semantic_similarity(resume.id, job_profile.raw_description)

        try:
            ai_result = await self.router.dispatch_json(
                stage="job_matching",
                prompt_key="job_matching_prompt",
                prompt_variables={
                    "job_profile_json": {
                        "title": job_profile.title,
                        "required_skills": job_profile.required_skills,
                        "preferred_skills": job_profile.preferred_skills,
                        "experience_level": job_profile.experience_level,
                        "responsibilities": job_profile.responsibilities,
                    },
                    "resume_parsed_json": {
                        "skills": resume.skills_extracted,
                        "experience": resume.experience_extracted,
                        "education": resume.education_extracted,
                    },
                    "keyword_overlap_pct": keyword_pct,
                    "semantic_similarity": semantic_pct if semantic_pct is not None else "unavailable",
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise ResumeMatchingFailedError(str(exc)) from exc

        ai_score = float(ai_result.get("ai_reasoning_score", 0) or 0)
        semantic_component = semantic_pct if semantic_pct is not None else keyword_pct  # graceful degradation
        final_score = round(
            _WEIGHT_SEMANTIC * semantic_component + _WEIGHT_KEYWORD * keyword_pct + _WEIGHT_AI_REASONING * ai_score,
            2,
        )

        return await self.repo.create(
            user_id=self.user_id,
            resume_id=resume.id,
            job_profile_id=job_profile.id,
            match_score=final_score,
            semantic_similarity=semantic_pct,
            keyword_overlap_pct=keyword_pct,
            ai_reasoning_score=ai_score,
            skill_overlap=ai_result.get("skill_overlap", []),
            missing_skills=ai_result.get("missing_skills", []),
            risk_factors=ai_result.get("risk_factors", []),
            recommendation=ai_result.get("recommendation"),
        )

    async def rank_resumes(self, resumes: list, job_profile) -> list[ResumeMatchResult]:
        results = []
        for resume in resumes:
            try:
                results.append(await self.match(resume, job_profile))
            except ResumeMatchingFailedError:
                logger.warning("resume_match_skipped", extra={"resume_id": str(resume.id)})
                continue
        results.sort(key=lambda r: r.match_score, reverse=True)
        return results
