"""AI Memory System — remembers past applications, resume versions used,
successful matches, rejected roles, and interview history, and feeds that
back into future resume selection, job matching, and email generation
decisions (per the master prompt's AI Memory System section).

Memory entries are short, structured summaries (not raw AI responses) so
they're cheap to inject into future prompt context.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_core.models import AIMemoryEntry, MemoryTypeEnum

logger = logging.getLogger("app.ai_core.memory")


class AIMemoryManager:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(
        self,
        *,
        user_id: uuid.UUID,
        memory_type: MemoryTypeEnum,
        summary: str,
        reference_id: uuid.UUID | None = None,
        payload: dict | None = None,
        outcome: str | None = None,
    ) -> AIMemoryEntry:
        entry = AIMemoryEntry(
            user_id=user_id,
            memory_type=memory_type,
            reference_id=reference_id,
            summary=summary,
            payload=payload or {},
            outcome=outcome,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def update_outcome(self, entry_id: uuid.UUID, outcome: str) -> None:
        entry = await self.session.get(AIMemoryEntry, entry_id)
        if entry:
            entry.outcome = outcome
            await self.session.flush()

    async def recent(
        self, user_id: uuid.UUID, memory_type: str | None = None, limit: int = 10
    ) -> list[AIMemoryEntry]:
        stmt = select(AIMemoryEntry).where(
            AIMemoryEntry.user_id == user_id, AIMemoryEntry.is_deleted.is_(False)
        )
        if memory_type:
            stmt = stmt.where(AIMemoryEntry.memory_type == memory_type)
        stmt = stmt.order_by(AIMemoryEntry.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def success_rate_for_resume(self, user_id: uuid.UUID, resume_id: uuid.UUID) -> float | None:
        """Fraction of past resume-version-used memory entries with a
        recorded successful outcome for a given resume. Returns None if
        there's no history yet (so callers can distinguish "0% success"
        from "no data").
        """
        stmt = select(AIMemoryEntry).where(
            AIMemoryEntry.user_id == user_id,
            AIMemoryEntry.memory_type == MemoryTypeEnum.RESUME_VERSION_USED,
            AIMemoryEntry.reference_id == resume_id,
            AIMemoryEntry.outcome.is_not(None),
            AIMemoryEntry.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        entries = list(result.scalars().all())
        if not entries:
            return None
        successes = sum(1 for e in entries if e.outcome == "success")
        return successes / len(entries)
