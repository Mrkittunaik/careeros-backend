"""Shared helpers for Mongo-backed 'documents'.

This project used to be Postgres/SQLAlchemy. It's now all-MongoDB. Instead
of a heavy ODM, each module defines plain Pydantic models (shape/validation
only) and a thin repository class that does the actual Motor queries. This
module provides the small pieces every document/repository shares: a UUID
id (kept as a string in Mongo, same UUID format as before so tokens/URLs
etc. didn't need to change), and the audit fields every table used to have.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MongoDocument(BaseModel):
    """Base for every document. Mirrors the old SQLAlchemy `Base`: id +
    created_at/updated_at + soft-delete + version.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    is_deleted: bool = False
    deleted_at: datetime | None = None
    version: int = 1

    def to_mongo(self) -> dict[str, Any]:
        """Serialize for storage: `id` -> `_id`, enums -> their value."""
        data = self.model_dump(mode="json")
        data["_id"] = data.pop("id")
        return data

    @classmethod
    def from_mongo(cls, doc: dict[str, Any] | None):
        if doc is None:
            return None
        doc = dict(doc)
        doc["id"] = doc.pop("_id")
        # BSON datetimes come back timezone-naive (always UTC on the wire).
        # Re-attach UTC tzinfo so comparisons against datetime.now(timezone.utc)
        # elsewhere in the app don't blow up with "can't compare offset-naive
        # and offset-aware datetimes".
        for key, value in list(doc.items()):
            if isinstance(value, datetime) and value.tzinfo is None:
                doc[key] = value.replace(tzinfo=timezone.utc)
        return cls(**doc)
