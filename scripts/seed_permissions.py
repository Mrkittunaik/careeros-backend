"""Seeds the default permission catalog and role -> permission grants.

Run with: python -m scripts.seed_permissions
"""
import asyncio

from app.auth.models import RoleEnum
from app.auth.repositories import PermissionRepository
from app.core.database import AsyncSessionLocal

DEFAULT_PERMISSIONS: list[tuple[str, str, str]] = [
    ("resume.read", "View resumes", "resume"),
    ("resume.write", "Create/edit resumes", "resume"),
    ("job.apply", "Apply to jobs", "job"),
    ("automation.run", "Trigger automation workflows", "automation"),
    ("email.read", "Read connected email accounts", "email"),
    ("email.send", "Send email via connected accounts", "email"),
    ("analytics.view", "View analytics dashboards", "analytics"),
    ("admin.panel.access", "Access the admin panel", "admin"),
]

ROLE_GRANTS: dict[RoleEnum, list[str]] = {
    RoleEnum.USER: ["resume.read", "resume.write", "job.apply"],
    RoleEnum.PREMIUM_USER: [
        "resume.read", "resume.write", "job.apply", "automation.run", "analytics.view",
    ],
    RoleEnum.ENTERPRISE_USER: [
        "resume.read", "resume.write", "job.apply", "automation.run",
        "email.read", "email.send", "analytics.view",
    ],
    RoleEnum.ADMIN: [
        "resume.read", "resume.write", "job.apply", "automation.run",
        "email.read", "email.send", "analytics.view", "admin.panel.access",
    ],
    RoleEnum.SYSTEM_SERVICE: ["automation.run", "email.read", "email.send"],
    # SUPER_ADMIN bypasses PBAC checks entirely (see RequirePermission).
}


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        repo = PermissionRepository(session)
        key_to_id = {}

        for key, description, category in DEFAULT_PERMISSIONS:
            existing = await repo.get_by_key(key)
            if existing:
                key_to_id[key] = existing.id
                continue
            created = await repo.create(key=key, description=description, category=category)
            key_to_id[key] = created.id
            print(f"created permission: {key}")

        for role, keys in ROLE_GRANTS.items():
            for key in keys:
                await repo.grant_to_role(role, key_to_id[key])
            print(f"granted {len(keys)} permissions to role {role.value}")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
