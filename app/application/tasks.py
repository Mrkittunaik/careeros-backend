import asyncio
import logging

from app.core.celery_app import celery_app

logger = logging.getLogger("app.application.tasks")


@celery_app.task(name="app.application.tasks.build_application_package", bind=True, max_retries=3)
def build_application_package(self, application_id: str, user_id: str) -> dict:
    """Async variant of ApplicationService.build_package, for callers (e.g.
    a bulk 'prepare all ready applications' action) that shouldn't block a
    request/response cycle on package assembly.
    """

    async def _run() -> dict:
        from app.application.service import ApplicationService
        from app.core.mongo import get_default_mongo_db

        service = ApplicationService(get_default_mongo_db())
        try:
            result = await service.build_package(user_id, application_id)
            return {
                "status": "ok",
                "is_complete": result["is_complete"],
                "missing_items": result["missing_items"],
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "application_package_build_failed",
                extra={"application_id": application_id, "user_id": user_id},
            )
            return {"status": "failed", "error": str(exc)}

    return asyncio.run(_run())


@celery_app.task(name="app.application.tasks.check_stale_applications", bind=True, max_retries=1)
def check_stale_applications(self) -> dict:
    """Periodic housekeeping task: flags applications that have sat in
    'applied' with no update for a long time, so the frontend can surface a
    "follow up?" nudge. Registered but not yet wired into celery beat by
    default — see app.core.celery_app.celery_app.conf.beat_schedule.
    """

    async def _run() -> dict:
        import datetime

        from app.application.enums import ApplicationStatusEnum
        from app.core.mongo import get_default_mongo_db

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)
        col = get_default_mongo_db()["applications"]

        count = await col.count_documents(
            {
                "status": ApplicationStatusEnum.APPLIED.value,
                "updated_at": {"$lt": cutoff},
                "is_deleted": False,
            }
        )
        logger.info("stale_applications_found", extra={"count": count})
        return {"stale_count": count}

    return asyncio.run(_run())
