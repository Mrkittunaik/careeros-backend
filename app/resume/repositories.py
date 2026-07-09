"""Resume module repositories — MongoDB (Motor) version.

Converted from SQLAlchemy/Postgres (old version kept as
repositories.py.postgres.bak). Method signatures are preserved wherever
reasonably possible; the main externally-visible change is that every id
parameter is now a plain `str` (Mongo's `_id`) instead of `uuid.UUID`,
matching the convention already used in app.application and app.autoapply.
Values are still valid UUID strings under the hood (MongoDocument.id
defaults to str(uuid4())), so nothing about ID *format* changed -- only
the Python type used to pass them around.
"""

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.mongo_base import utcnow
from app.resume.models import (
    AIProviderEnum,
    Resume,
    ResumeAIAnalysis,
    ResumeATSReport,
    ResumeJobMatch,
    ResumeSelectionLog,
    ResumeSelectionRule,
    ResumeStatusEnum,
    UserAIProviderKey,
)


class ResumeRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["resumes"]

    async def get_by_id(self, resume_id: str) -> Resume | None:
        doc = await self.col.find_one({"_id": str(resume_id), "is_deleted": False})
        return Resume.from_mongo(doc)

    async def get_owned(self, resume_id: str, user_id: str) -> Resume | None:
        doc = await self.col.find_one(
            {"_id": str(resume_id), "user_id": str(user_id), "is_deleted": False}
        )
        return Resume.from_mongo(doc)

    async def list_for_user(
        self,
        user_id: str,
        *,
        tags: list[str] | None = None,
        status: ResumeStatusEnum | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Resume], int]:
        filt: dict = {"user_id": str(user_id), "is_deleted": False}
        if status:
            filt["status"] = status.value if isinstance(status, ResumeStatusEnum) else status
        if tags:
            # Mongo equivalent of the old JSONB "contains any of" check:
            # resume.tags must include at least one requested tag.
            filt["tags"] = {"$in": tags}

        total = await self.col.count_documents(filt)

        cursor = self.col.find(filt).sort("updated_at", -1).skip(offset).limit(limit)
        rows = [Resume.from_mongo(doc) async for doc in cursor]
        return rows, total

    async def count_for_user(self, user_id: str) -> int:
        return await self.col.count_documents({"user_id": str(user_id), "is_deleted": False})

    async def create(self, **kwargs) -> Resume:
        resume = Resume(**kwargs)
        await self.col.insert_one(resume.to_mongo())
        return resume

    async def update_fields(self, resume_id: str, **kwargs) -> None:
        kwargs["updated_at"] = utcnow()
        await self.col.update_one({"_id": str(resume_id)}, {"$set": kwargs})

    async def set_status(self, resume_id: str, status: ResumeStatusEnum, failure_reason: str | None = None) -> None:
        values: dict = {"status": status.value, "updated_at": utcnow()}
        if failure_reason is not None:
            values["failure_reason"] = failure_reason
        await self.col.update_one({"_id": str(resume_id)}, {"$set": values})

    async def soft_delete(self, resume_id: str) -> None:
        await self.col.update_one(
            {"_id": str(resume_id)},
            {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc), "is_active": False}},
        )

    async def get_version_chain(self, resume_id: str) -> list[Resume]:
        """Walks up to the root parent then returns the full version chain,
        ordered oldest -> newest.
        """
        resume = await self.get_by_id(resume_id)
        if not resume:
            return []
        current = resume
        while current.parent_resume_id:
            parent = await self.get_by_id(current.parent_resume_id)
            if not parent:
                break
            current = parent
        root_id = current.id

        cursor = self.col.find(
            {
                "$or": [{"_id": root_id}, {"parent_resume_id": root_id}],
                "is_deleted": False,
            }
        ).sort("version_number", 1)
        return [Resume.from_mongo(doc) async for doc in cursor]

    async def next_version_number(self, root_or_related_id: str) -> int:
        chain = await self.get_version_chain(root_or_related_id)
        if not chain:
            return 1
        return max(r.version_number for r in chain) + 1


class ResumeAIAnalysisRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["resume_ai_analyses"]

    async def create(self, resume_id: str, provider_used: AIProviderEnum, **kwargs) -> ResumeAIAnalysis:
        analysis = ResumeAIAnalysis(resume_id=str(resume_id), provider_used=provider_used, **kwargs)
        await self.col.insert_one(analysis.to_mongo())
        return analysis

    async def get_latest(self, resume_id: str) -> ResumeAIAnalysis | None:
        doc = await self.col.find_one(
            {"resume_id": str(resume_id), "is_deleted": False},
            sort=[("created_at", -1)],
        )
        return ResumeAIAnalysis.from_mongo(doc)


class ResumeATSReportRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["resume_ats_reports"]

    async def create(self, resume_id: str, **kwargs) -> ResumeATSReport:
        report = ResumeATSReport(resume_id=str(resume_id), **kwargs)
        await self.col.insert_one(report.to_mongo())
        return report

    async def get_latest(self, resume_id: str) -> ResumeATSReport | None:
        doc = await self.col.find_one(
            {"resume_id": str(resume_id), "is_deleted": False},
            sort=[("created_at", -1)],
        )
        return ResumeATSReport.from_mongo(doc)


class ResumeJobMatchRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["resume_job_matches"]

    async def create(self, resume_id: str, **kwargs) -> ResumeJobMatch:
        match = ResumeJobMatch(resume_id=str(resume_id), **kwargs)
        await self.col.insert_one(match.to_mongo())
        return match

    async def list_for_resume(self, resume_id: str, limit: int = 20) -> list[ResumeJobMatch]:
        cursor = (
            self.col.find({"resume_id": str(resume_id), "is_deleted": False})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [ResumeJobMatch.from_mongo(doc) async for doc in cursor]


class ResumeSelectionRuleRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["resume_selection_rules"]

    async def list_for_user(self, user_id: str, active_only: bool = True) -> list[ResumeSelectionRule]:
        filt: dict = {"user_id": str(user_id), "is_deleted": False}
        if active_only:
            filt["is_active"] = True
        cursor = self.col.find(filt).sort("priority", -1)
        return [ResumeSelectionRule.from_mongo(doc) async for doc in cursor]

    async def create(self, **kwargs) -> ResumeSelectionRule:
        rule = ResumeSelectionRule(**kwargs)
        await self.col.insert_one(rule.to_mongo())
        return rule

    async def get_owned(self, rule_id: str, user_id: str) -> ResumeSelectionRule | None:
        doc = await self.col.find_one(
            {"_id": str(rule_id), "user_id": str(user_id), "is_deleted": False}
        )
        return ResumeSelectionRule.from_mongo(doc)

    async def delete(self, rule_id: str) -> None:
        await self.col.update_one(
            {"_id": str(rule_id)},
            {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc)}},
        )


class ResumeSelectionLogRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["resume_selection_logs"]

    async def create(self, **kwargs) -> ResumeSelectionLog:
        log = ResumeSelectionLog(**kwargs)
        await self.col.insert_one(log.to_mongo())
        return log

    async def success_rate_for_resume(self, resume_id: str) -> float | None:
        cursor = self.col.find(
            {
                "resume_id": str(resume_id),
                "was_successful": {"$ne": None},
                "is_deleted": False,
            }
        )
        rows = [ResumeSelectionLog.from_mongo(doc) async for doc in cursor]
        if not rows:
            return None
        successes = sum(1 for r in rows if r.was_successful)
        return round(successes / len(rows) * 100, 2)


class UserAIProviderKeyRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["user_ai_provider_keys"]

    async def list_for_user(self, user_id: str) -> list[UserAIProviderKey]:
        cursor = self.col.find({"user_id": str(user_id), "is_deleted": False})
        return [UserAIProviderKey.from_mongo(doc) async for doc in cursor]

    async def get_by_provider(self, user_id: str, provider: AIProviderEnum) -> UserAIProviderKey | None:
        provider_value = provider.value if isinstance(provider, AIProviderEnum) else provider
        doc = await self.col.find_one(
            {"user_id": str(user_id), "provider": provider_value, "is_deleted": False}
        )
        return UserAIProviderKey.from_mongo(doc)

    async def upsert(self, user_id: str, provider: AIProviderEnum, encrypted_api_key: str) -> UserAIProviderKey:
        existing = await self.get_by_provider(user_id, provider)
        if existing:
            await self.col.update_one(
                {"_id": existing.id},
                {"$set": {"encrypted_api_key": encrypted_api_key, "is_active": True, "updated_at": utcnow()}},
            )
            existing.encrypted_api_key = encrypted_api_key
            existing.is_active = True
            return existing
        key_row = UserAIProviderKey(user_id=str(user_id), provider=provider, encrypted_api_key=encrypted_api_key)
        await self.col.insert_one(key_row.to_mongo())
        return key_row

    async def delete(self, user_id: str, provider: AIProviderEnum) -> bool:
        existing = await self.get_by_provider(user_id, provider)
        if not existing:
            return False
        await self.col.update_one(
            {"_id": existing.id},
            {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc)}},
        )
        return True
