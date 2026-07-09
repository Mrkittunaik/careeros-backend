"""Email Analysis Engine — analyzes incoming application-related emails:
status classification, interview intelligence, rejection intelligence, per
the master prompt's Email Analysis Engine / Status Classification System /
Rejection Intelligence / Interview Intelligence sections.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.context_builder import clean_text
from app.ai_core.exceptions import EmailAnalysisFailedError
from app.ai_core.memory import AIMemoryManager
from app.ai_core.models import EmailAnalysisResult, EmailStatusEnum, InterviewTypeEnum, MemoryTypeEnum
from app.ai_core.orchestrator import AIRouter
from app.ai_core.repositories import EmailAnalysisRepository

logger = logging.getLogger("app.ai_core.email_analysis")

_VALID_STATUSES = {s.value for s in EmailStatusEnum}
_VALID_INTERVIEW_TYPES = {t.value for t in InterviewTypeEnum}


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("email_analysis_bad_datetime", extra={"value": value})
        return None


class EmailAnalysisEngine:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID):
        self.session = session
        self.user_id = user_id
        self.router = AIRouter(session, user_id=user_id)
        self.repo = EmailAnalysisRepository(session)
        self.memory = AIMemoryManager(session)

    async def analyze(self, email_text: str, source_email_id: uuid.UUID | None = None) -> EmailAnalysisResult:
        cleaned = clean_text(email_text)
        try:
            result = await self.router.dispatch_json(
                stage="email_analysis",
                prompt_key="email_analysis_prompt",
                prompt_variables={"email_text": cleaned[:6000]},
                use_cache=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise EmailAnalysisFailedError(str(exc)) from exc

        status_raw = str(result.get("status_classification") or "no_response").lower()
        status = EmailStatusEnum(status_raw) if status_raw in _VALID_STATUSES else EmailStatusEnum.NO_RESPONSE

        interview_type_raw = result.get("interview_type")
        interview_type = None
        if interview_type_raw and str(interview_type_raw).lower() in _VALID_INTERVIEW_TYPES:
            interview_type = InterviewTypeEnum(str(interview_type_raw).lower())

        rejection_reason = result.get("rejection_reason")
        if status == EmailStatusEnum.REJECTED and not rejection_reason:
            rejection_reason = "No reason provided"

        analysis = await self.repo.create(
            user_id=self.user_id,
            source_email_id=source_email_id,
            raw_email_text=email_text,
            status_classification=status,
            confidence_score=float(result.get("confidence_score", 0) or 0),
            company_name=result.get("company_name"),
            job_title=result.get("job_title"),
            recruiter_name=result.get("recruiter_name"),
            interview_type=interview_type,
            interview_datetime=_parse_iso_datetime(result.get("interview_date")),
            meeting_platform=result.get("meeting_platform"),
            meeting_link=result.get("meeting_link"),
            duration_minutes=result.get("duration_minutes"),
            interviewer_details=result.get("interviewer_details", []),
            rejection_reason=rejection_reason,
            missing_skills=result.get("missing_skills", []),
            feedback=result.get("feedback"),
            future_recommendation=result.get("future_recommendation"),
            provider_used=result.get("_provider_used"),
            raw_ai_response=result,
        )

        await self._record_memory(analysis)
        return analysis

    async def _record_memory(self, analysis: EmailAnalysisResult) -> None:
        """Feeds interview/rejection outcomes back into AI Memory so future
        resume selection and job matching can learn from them.
        """
        if analysis.status_classification == EmailStatusEnum.REJECTED:
            await self.memory.record(
                user_id=self.user_id,
                memory_type=MemoryTypeEnum.REJECTED_ROLE,
                summary=f"Rejected for {analysis.job_title or 'a role'} at {analysis.company_name or 'a company'}: "
                f"{analysis.rejection_reason}",
                reference_id=analysis.id,
                payload={"missing_skills": analysis.missing_skills, "company": analysis.company_name},
                outcome="failure",
            )
        elif analysis.status_classification in (
            EmailStatusEnum.INTERVIEW_SCHEDULED,
            EmailStatusEnum.OFFER_RECEIVED,
            EmailStatusEnum.SHORTLISTED,
        ):
            await self.memory.record(
                user_id=self.user_id,
                memory_type=MemoryTypeEnum.INTERVIEW_HISTORY,
                summary=f"{analysis.status_classification.value} for {analysis.job_title or 'a role'} at "
                f"{analysis.company_name or 'a company'}",
                reference_id=analysis.id,
                payload={"interview_type": analysis.interview_type.value if analysis.interview_type else None},
                outcome="success" if analysis.status_classification == EmailStatusEnum.OFFER_RECEIVED else None,
            )
