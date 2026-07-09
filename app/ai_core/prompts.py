"""Prompt Management System — the single source of truth for every prompt
used by the AI Engine.

Per the master prompt, prompts must support versioning, dynamic variables,
role-based customization, localization (future), and A/B testing (future).
This module provides hardcoded, version-1 defaults for every prompt
category; `PromptManager` resolves the active prompt for a key by checking
`ai_prompt_templates` in the DB first (so prompts can be tuned without a
redeploy) and falling back to these defaults otherwise.

Every prompt is defined with `{variable}` placeholders filled via
`.format(**variables)` — never raw string concatenation — so injected
context stays structured and auditable.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.models import PromptTemplate

logger = logging.getLogger("app.ai_core.prompts")


@dataclass(frozen=True)
class ResolvedPrompt:
    key: str
    version: int
    system_prompt: str
    user_prompt_template: str
    source: str  # "db" | "default"


# --- Default (version 1) prompt registry -----------------------------------
# Keys match the master prompt's required categories exactly.

_DEFAULTS: dict[str, ResolvedPrompt] = {
    "job_description_understanding_prompt": ResolvedPrompt(
        key="job_description_understanding_prompt",
        version=1,
        system_prompt=(
            "You are a job intelligence engine. You extract structured, factual data from job "
            "postings. Infer hidden/implicit requirements only when strongly implied by the text "
            "(e.g. 'fast-paced startup' implies adaptability), and label those clearly as inferred. "
            "Respond with strict JSON only, no markdown, no commentary."
        ),
        user_prompt_template=(
            "Analyze this job posting and extract a structured profile.\n\n"
            "Job posting:\n\"\"\"\n{job_description}\n\"\"\"\n\n"
            "Return JSON:\n"
            "{{\n"
            '  "title": "string or null",\n'
            '  "company": "string or null",\n'
            '  "required_skills": ["skill1"],\n'
            '  "preferred_skills": ["skill1"],\n'
            '  "experience_level": "entry|mid|senior|lead|unknown",\n'
            '  "salary_range": {{"min": null, "max": null, "currency": null}},\n'
            '  "job_type": "remote|hybrid|onsite|unknown",\n'
            '  "responsibilities": ["responsibility1"],\n'
            '  "ats_keywords": ["keyword1"],\n'
            '  "hidden_requirements": ["inferred requirement 1"]\n'
            "}}"
        ),
        source="default",
    ),
    "job_matching_prompt": ResolvedPrompt(
        key="job_matching_prompt",
        version=1,
        system_prompt=(
            "You are a resume-to-job matching reasoning engine. You are given a job profile and a "
            "resume, plus pre-computed keyword-overlap and semantic-similarity signals. Reason about "
            "fit qualitatively and produce a calibrated AI reasoning score. Respond with strict JSON only."
        ),
        user_prompt_template=(
            "Job profile: {job_profile_json}\n\n"
            "Resume parsed data: {resume_parsed_json}\n\n"
            "Pre-computed signals — keyword overlap: {keyword_overlap_pct}%, "
            "semantic similarity: {semantic_similarity}\n\n"
            "Return JSON:\n"
            "{{\n"
            '  "ai_reasoning_score": 0-100,\n'
            '  "skill_overlap": ["skill1"],\n'
            '  "missing_skills": ["skill1"],\n'
            '  "risk_factors": ["e.g. under-qualified for seniority level"],\n'
            '  "recommendation": "1-2 sentence human-readable recommendation"\n'
            "}}"
        ),
        source="default",
    ),
    "cover_letter_prompt": ResolvedPrompt(
        key="cover_letter_prompt",
        version=1,
        system_prompt=(
            "You are a professional cover letter writer. You NEVER invent experience, skills, or "
            "achievements not present in the candidate's resume data. You adapt tone to the company "
            "and role. Respond with strict JSON only."
        ),
        user_prompt_template=(
            "Write a cover letter.\n\n"
            "Candidate resume data: {resume_parsed_json}\n\n"
            "Company: {company_name}\nRole: {role_title}\nJob description: {job_description}\n"
            "Desired tone: {tone}\n\n"
            "Return JSON:\n"
            '{{\n  "cover_letter": "full cover letter text",\n  "notes": "any grounding caveats"\n}}'
        ),
        source="default",
    ),
    "cold_email_prompt": ResolvedPrompt(
        key="cold_email_prompt",
        version=1,
        system_prompt=(
            "You are a cold outreach email writer for job seekers. Emails must be polite, short "
            "(under 150 words), have a clear intent, and a clear call to action. Never invent facts "
            "about the candidate. Respond with strict JSON only."
        ),
        user_prompt_template=(
            "Write a cold outreach email to a recruiter.\n\n"
            "Job role: {role_title}\nCompany: {company_name}\n"
            "Recruiter info: {recruiter_info}\nResume summary: {resume_summary}\n\n"
            "Return JSON:\n"
            "{{\n"
            '  "subject": "short subject line",\n'
            '  "body": "email body",\n'
            '  "follow_up_body": "shorter follow-up email for 5-7 days later"\n'
            "}}"
        ),
        source="default",
    ),
    "email_analysis_prompt": ResolvedPrompt(
        key="email_analysis_prompt",
        version=1,
        system_prompt=(
            "You are an email analysis engine for a job application tracker. You classify inbound "
            "emails and extract structured facts. Only extract what is explicitly present or "
            "unambiguously implied; never fabricate dates, names, or links. Respond with strict JSON only."
        ),
        user_prompt_template=(
            "Analyze this email related to a job application.\n\n"
            "Email:\n\"\"\"\n{email_text}\n\"\"\"\n\n"
            "Return JSON:\n"
            "{{\n"
            '  "status_classification": "applied|under_review|shortlisted|interview_scheduled|'
            'assessment_sent|offer_received|rejected|no_response|follow_up_required",\n'
            '  "confidence_score": 0-100,\n'
            '  "company_name": "string or null",\n'
            '  "job_title": "string or null",\n'
            '  "recruiter_name": "string or null",\n'
            '  "interview_type": "hr|technical|system_design|managerial|unknown|null",\n'
            '  "interview_date": "ISO 8601 datetime string or null",\n'
            '  "meeting_platform": "zoom|meet|teams|other|null",\n'
            '  "meeting_link": "string or null",\n'
            '  "duration_minutes": "integer or null",\n'
            '  "interviewer_details": [{{"name": "", "role": ""}}],\n'
            '  "rejection_reason": "string or null — \'No reason provided\' if rejected with no reason given",\n'
            '  "missing_skills": ["skill1"],\n'
            '  "feedback": "string or null",\n'
            '  "future_recommendation": "string or null"\n'
            "}}"
        ),
        source="default",
    ),
    "resume_analysis_prompt": ResolvedPrompt(
        key="resume_analysis_prompt",
        version=1,
        system_prompt=(
            "You are a senior technical recruiter and resume analyst. Be honest and specific. "
            "Respond with strict JSON only."
        ),
        user_prompt_template=(
            "Analyze this resume.\n\nParsed data: {resume_parsed_json}\n\nResume text:\n\"\"\"\n{raw_text}\n\"\"\"\n\n"
            "Return JSON:\n"
            "{{\n"
            '  "classification": "most likely target job role/title",\n'
            '  "experience_score": 0-100,\n'
            '  "strengths": ["specific strength 1"],\n'
            '  "weaknesses": ["specific weakness 1"],\n'
            '  "missing_skills": ["skill commonly expected but absent"],\n'
            '  "rewrite_suggestions": ["actionable bullet-point rewrite suggestion 1"]\n'
            "}}"
        ),
        source="default",
    ),
    "interview_detection_prompt": ResolvedPrompt(
        key="interview_detection_prompt",
        version=1,
        system_prompt=(
            "You are an interview-scheduling detail extractor. Extract only facts explicitly stated. "
            "Respond with strict JSON only."
        ),
        user_prompt_template=(
            "Extract interview scheduling details from this email.\n\nEmail:\n\"\"\"\n{email_text}\n\"\"\"\n\n"
            "Return JSON:\n"
            "{{\n"
            '  "interview_type": "hr|technical|system_design|managerial|unknown",\n'
            '  "interview_date": "ISO 8601 datetime string or null",\n'
            '  "platform": "zoom|meet|teams|other|null",\n'
            '  "duration_minutes": "integer or null",\n'
            '  "interviewer_details": [{{"name": "", "role": ""}}]\n'
            "}}"
        ),
        source="default",
    ),
    "rejection_detection_prompt": ResolvedPrompt(
        key="rejection_detection_prompt",
        version=1,
        system_prompt=(
            "You are a rejection-email intelligence extractor. Never invent a reason that isn't "
            "stated or clearly implied. Respond with strict JSON only."
        ),
        user_prompt_template=(
            "Extract rejection details from this email.\n\nEmail:\n\"\"\"\n{email_text}\n\"\"\"\n\n"
            "Return JSON:\n"
            "{{\n"
            '  "reason": "string, or \'No reason provided\' if absent",\n'
            '  "missing_skills": ["skill1"],\n'
            '  "feedback": "string or null",\n'
            '  "future_recommendation": "string or null"\n'
            "}}"
        ),
        source="default",
    ),
    "application_answer_prompt": ResolvedPrompt(
        key="application_answer_prompt",
        version=1,
        system_prompt=(
            "You are an expert career coach helping a job applicant answer a specific "
            "application-form question. Write a concise, specific, first-person answer "
            "grounded only in the candidate's actual resume content provided below. "
            "Do not invent experience, companies, or metrics that are not present in "
            "the resume data. Respond with strict JSON only."
        ),
        user_prompt_template=(
            "Question: {question}\n\n"
            "Word limit: {word_limit}\n\n"
            "Company: {company_name}\nRole: {role_title}\nJob description: {job_description}\n\n"
            "Candidate resume summary:\n"
            "Skills: {skills}\nExperience: {experience}\nProjects: {projects}\n"
            "Certifications: {certifications}\n\n"
            "Return JSON:\n"
            '{{\n  "answer": "the answer text"\n}}'
        ),
        source="default",
    ),
}


class PromptManager:
    """Resolves the active prompt for a given key: DB override (highest
    version, active) first, else the hardcoded default. Caches per-instance
    to avoid repeat DB round-trips within a single request/task.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._cache: dict[str, ResolvedPrompt] = {}

    async def resolve(self, key: str) -> ResolvedPrompt:
        if key in self._cache:
            return self._cache[key]

        stmt = (
            select(PromptTemplate)
            .where(PromptTemplate.key == key, PromptTemplate.is_active.is_(True), PromptTemplate.is_deleted.is_(False))
            .order_by(PromptTemplate.version.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()

        if row:
            resolved = ResolvedPrompt(
                key=row.key,
                version=row.version,
                system_prompt=row.system_prompt,
                user_prompt_template=row.user_prompt_template,
                source="db",
            )
        elif key in _DEFAULTS:
            resolved = _DEFAULTS[key]
        else:
            from app.ai_core.exceptions import PromptTemplateNotFoundError

            raise PromptTemplateNotFoundError(key)

        self._cache[key] = resolved
        return resolved

    async def render(self, key: str, **variables) -> tuple[str, str, ResolvedPrompt]:
        """Returns (system_prompt, rendered_user_prompt, resolved_metadata)."""
        resolved = await self.resolve(key)
        try:
            user_prompt = resolved.user_prompt_template.format(**variables)
        except KeyError as exc:
            logger.error("prompt_render_missing_variable", extra={"key": key, "missing": str(exc)})
            raise
        return resolved.system_prompt, user_prompt, resolved
