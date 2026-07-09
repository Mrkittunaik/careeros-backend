import difflib

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.application.enums import TERMINAL_STATUSES, ApplicationStatusEnum
from app.application.models import Application
from app.application.repository import ApplicationRepository

EXACT_MATCH_CONFIDENCE = 95.0
FUZZY_MATCH_MIN_CONFIDENCE = 55.0
TITLE_SIMILARITY_WEIGHT = 0.5
COMPANY_SIMILARITY_WEIGHT = 0.5


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


class EmailApplicationMatcher:
    """Matches an ingested, classified email to an existing Application
    using company name + job title, per the spec's Status Tracking Engine
    ("Use job title + company matching. Use semantic similarity if needed")
    and Job Matching From Emails sections.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.app_repo = ApplicationRepository(db)

    async def find_match(
        self, *, user_id: str, company_name: str | None, job_title: str | None, thread_linked_application_id: str | None = None
    ) -> tuple[Application | None, float, str]:
        """Returns (application, confidence_0_to_100, method)."""
        # 1. Same-thread emails inherit the thread's linked application —
        #    cheapest and most reliable signal (Email Thread Tracking).
        if thread_linked_application_id:
            app = await self.app_repo.get_owned(thread_linked_application_id, user_id)
            if app:
                return app, 100.0, "thread"

        if not company_name and not job_title:
            return None, 0.0, "none"

        candidates, _total = await self.app_repo.search(
            user_id,
            company_name=company_name,
            include_terminal=True,
            limit=25,
        )
        if not candidates:
            return None, 0.0, "none"

        norm_company = _normalize(company_name)
        norm_title = _normalize(job_title)

        best_app: Application | None = None
        best_score = 0.0
        for app in candidates:
            company_sim = _similarity(norm_company, _normalize(app.company_name))
            title_sim = _similarity(norm_title, _normalize(app.role_title)) if job_title else 0.5
            score = (company_sim * COMPANY_SIMILARITY_WEIGHT + title_sim * TITLE_SIMILARITY_WEIGHT) * 100

            if norm_company and norm_company == _normalize(app.company_name):
                score = max(score, EXACT_MATCH_CONFIDENCE if not job_title else score)

            if score > best_score:
                best_score = score
                best_app = app

        if best_app and best_score >= FUZZY_MATCH_MIN_CONFIDENCE:
            method = "exact" if best_score >= EXACT_MATCH_CONFIDENCE else "fuzzy"
            return best_app, round(best_score, 2), method

        return None, round(best_score, 2), "none"

    @staticmethod
    def is_regression(current_status: ApplicationStatusEnum, candidate_status: ApplicationStatusEnum) -> bool:
        """Prevents e.g. an 'under_review' auto-parse email from bumping an
        application backwards after it already reached OFFER/INTERVIEW."""
        if current_status in TERMINAL_STATUSES:
            return True
        rank = {
            ApplicationStatusEnum.SUBMITTED: 0,
            ApplicationStatusEnum.APPLIED: 0,
            ApplicationStatusEnum.VIEWED: 1,
            ApplicationStatusEnum.UNDER_REVIEW: 2,
            ApplicationStatusEnum.ASSESSMENT: 3,
            ApplicationStatusEnum.INTERVIEW: 4,
            ApplicationStatusEnum.OFFER: 5,
        }
        return rank.get(candidate_status, 0) < rank.get(current_status, 0)
