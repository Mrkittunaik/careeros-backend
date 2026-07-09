"""AI Resume Engine — the intelligence core of the Resume Intelligence System.

Every method here goes through AIProviderManager.complete_json so provider
fallback (Groq -> OpenAI -> Gemini -> Claude -> Ollama, BYOK-aware) is
centralized. AI is never allowed to fabricate experience — prompts
explicitly instruct "only reorganize/rephrase what is present, never invent
facts", per the master prompt's optimization-engine constraint.

MongoDB migration note: this class holds no direct database calls itself
(it never did) -- it only constructs an AIProviderManager, which now takes
a Motor database handle instead of a SQLAlchemy AsyncSession. All prompt
building and orchestration logic below is unchanged.
"""

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.resume.ai_providers import AIProviderManager, ProviderCallError
from app.resume.exceptions import ATSScoringFailedError, JobMatchingFailedError, ResumeParsingFailedError
from app.resume.parsing import regex_extract_hints

logger = logging.getLogger("app.resume.ai_engine")


class AIResumeEngine:
    def __init__(self, db: AsyncIOMotorDatabase, user_id: str | None = None):
        self.db = db
        self.provider_manager = AIProviderManager(db, user_id=user_id)

    # ------------------------------------------------------------------
    # 1. Structured extraction (parsing engine's LLM half)
    # ------------------------------------------------------------------
    async def extract_structured_data(self, raw_text: str) -> dict:
        """Extracts skills, experience, education, projects, certifications
        as structured JSON. Regex hints are passed in as grounding context.
        """
        hints = regex_extract_hints(raw_text)
        system_prompt = (
            "You are a precise resume parser. Extract ONLY information that is "
            "explicitly present in the resume text. Never invent, infer, or embellish "
            "facts. Respond with strict JSON only, no markdown, no commentary."
        )
        user_prompt = f"""Extract structured data from this resume text.

Grounding hints already detected (use to cross-check, not replace):
{hints}

Resume text:
\"\"\"
{raw_text[:12000]}
\"\"\"

Return JSON with exactly this shape:
{{
  "name": "string or null",
  "email": "string or null",
  "phone": "string or null",
  "skills": ["skill1", "skill2"],
  "experience": [{{"title": "", "company": "", "duration": "", "description": ""}}],
  "education": [{{"degree": "", "institution": "", "year": ""}}],
  "projects": [{{"name": "", "description": "", "technologies": []}}],
  "certifications": ["cert1"],
  "tools_technologies": ["tool1"],
  "achievements": ["achievement1"]
}}"""
        try:
            data, provider = await self.provider_manager.complete_json(system_prompt, user_prompt)
            return {"parsed": data, "provider_used": provider.value, "hints": hints}
        except ProviderCallError as exc:
            logger.warning("ai_extraction_fallback_to_regex_only", extra={"error": str(exc)})
            # Graceful degradation: regex hints only, structured lists empty.
            return {
                "parsed": {
                    "name": hints.get("name_guess"),
                    "email": hints.get("email"),
                    "phone": hints.get("phone"),
                    "skills": [],
                    "experience": [],
                    "education": [],
                    "projects": [],
                    "certifications": [],
                    "tools_technologies": [],
                    "achievements": [],
                },
                "provider_used": None,
                "hints": hints,
            }

    # ------------------------------------------------------------------
    # 2. Classification + experience scoring + strengths/weaknesses
    # ------------------------------------------------------------------
    async def analyze_resume(self, raw_text: str, parsed_json: dict) -> dict:
        system_prompt = (
            "You are a senior technical recruiter and resume analyst. Be honest and "
            "specific. Respond with strict JSON only."
        )
        user_prompt = f"""Analyze this resume.

Parsed data: {parsed_json}

Resume text (for tone/context):
\"\"\"
{raw_text[:8000]}
\"\"\"

Return JSON:
{{
  "classification": "most likely target job role/title, e.g. 'Backend Developer'",
  "experience_score": 0-100,
  "strengths": ["specific strength 1", "..."],
  "weaknesses": ["specific weakness 1", "..."],
  "missing_skills": ["skill commonly expected for this role but absent"],
  "rewrite_suggestions": ["actionable bullet-point rewrite suggestion 1", "..."]
}}"""
        try:
            data, provider = await self.provider_manager.complete_json(system_prompt, user_prompt)
            data["provider_used"] = provider.value
            return data
        except ProviderCallError as exc:
            raise ResumeParsingFailedError(f"AI analysis failed: {exc}") from exc

    # ------------------------------------------------------------------
    # 3. ATS scoring engine
    # ------------------------------------------------------------------
    async def score_ats(self, raw_text: str, parsed_json: dict, job_description: str | None = None) -> dict:
        system_prompt = (
            "You are an ATS (Applicant Tracking System) simulation engine. Score "
            "resumes the way real ATS software does: keyword matching, format "
            "compatibility, and structural parseability. Respond with strict JSON only."
        )
        jd_block = f'\nJob description to match against:\n"""\n{job_description[:6000]}\n"""' if job_description else "\nNo specific job description provided — score for general ATS compatibility."
        user_prompt = f"""Score this resume for ATS compatibility.

Parsed data: {parsed_json}

Resume text:
\"\"\"
{raw_text[:8000]}
\"\"\"
{jd_block}

Return JSON:
{{
  "overall_score": 0-100,
  "keyword_match_score": 0-100,
  "skill_relevance_score": 0-100,
  "experience_relevance_score": 0-100,
  "format_compatibility_score": 0-100,
  "readability_score": 0-100,
  "missing_keywords": ["keyword1", "..."],
  "suggestions": ["specific improvement suggestion 1", "..."]
}}"""
        try:
            data, provider = await self.provider_manager.complete_json(system_prompt, user_prompt)
            data["provider_used"] = provider.value
            return data
        except ProviderCallError as exc:
            raise ATSScoringFailedError(str(exc)) from exc

    # ------------------------------------------------------------------
    # 4. Job-resume matching engine
    # ------------------------------------------------------------------
    async def match_job(self, raw_text: str, parsed_json: dict, job_description: str, job_role_title: str | None = None) -> dict:
        system_prompt = (
            "You are a resume-to-job matching engine. Be precise and quantitative. "
            "Respond with strict JSON only."
        )
        user_prompt = f"""Compare this resume against the job description and compute a match.

Job role: {job_role_title or "not specified"}
Job description:
\"\"\"
{job_description[:6000]}
\"\"\"

Resume parsed data: {parsed_json}

Resume text:
\"\"\"
{raw_text[:8000]}
\"\"\"

Return JSON:
{{
  "match_percentage": 0-100,
  "skill_overlap": ["matching skill 1", "..."],
  "missing_requirements": ["requirement not met 1", "..."],
  "experience_fit_score": 0-100,
  "recommendation_score": 0-100
}}"""
        try:
            data, provider = await self.provider_manager.complete_json(system_prompt, user_prompt)
            data["provider_used"] = provider.value
            return data
        except ProviderCallError as exc:
            raise JobMatchingFailedError(str(exc)) from exc

    # ------------------------------------------------------------------
    # 5. Resume optimization engine
    # ------------------------------------------------------------------
    async def optimize_resume(self, raw_text: str, parsed_json: dict, target_job_description: str | None = None) -> dict:
        system_prompt = (
            "You are a resume optimization assistant. You ONLY enhance presentation "
            "and phrasing of information already present. You NEVER fabricate new "
            "experience, skills, or achievements that are not grounded in the source "
            "resume. Respond with strict JSON only."
        )
        jd_block = f'\nOptimize toward this target job description:\n"""\n{target_job_description[:6000]}\n"""' if target_job_description else ""
        user_prompt = f"""Optimize this resume's presentation without inventing facts.

Parsed data: {parsed_json}

Resume text:
\"\"\"
{raw_text[:8000]}
\"\"\"
{jd_block}

Return JSON:
{{
  "rewritten_bullets": [{{"original": "", "improved": ""}}],
  "ats_keyword_additions": ["keyword to naturally weave in, only if truthful"],
  "formatting_suggestions": ["suggestion 1", "..."],
  "job_targeting_notes": "how to angle this resume toward the target role"
}}"""
        try:
            data, provider = await self.provider_manager.complete_json(system_prompt, user_prompt)
            data["provider_used"] = provider.value
            return data
        except ProviderCallError as exc:
            raise ResumeParsingFailedError(f"AI optimization failed: {exc}") from exc
