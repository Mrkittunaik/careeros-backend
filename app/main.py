from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import RequestContextMiddleware, configure_logging
from app.health.router import router as health_router
from app.integrations.router import router as integrations_router

from app.application.router import router as application_router
from app.resume.router import router as resume_router

# --- MIGRATION IN PROGRESS: Postgres -> MongoDB ---
# core, auth, integrations, application, and resume are fully converted to
# MongoDB and live below. email_comm has ALSO been fully converted to
# MongoDB in this pass (models/repository/service/router/tasks/schemas are
# all Motor-based now — see app/email_comm/*.py and the .postgres.bak
# files for the old versions) but its router is intentionally still
# commented out below: EmailIngestionService imports
# app.ai_core.email_analysis.EmailAnalysisEngine for AI classification of
# incoming emails, and app.ai_core itself is still SQLAlchemy/Postgres-
# backed (its models.py does `from app.core.database import Base`, which
# no longer exists now that app.core.database is Mongo-only). Importing
# app.email_comm.router right now would therefore break app startup, not
# because of anything in email_comm itself, but because of this one
# upstream dependency. Uncomment `email_router` below as soon as ai_core
# is converted in its own pass — no other changes to email_comm should be
# needed at that point.
#   from app.ai_core.router import router as ai_core_router
#   from app.email_comm.router import router as email_router
#   from app.notification.router import reports_router as reports_router
#   from app.notification.router import router as notification_router
#   from app.notification.router import scheduler_router as scheduler_router
#
# NOTE: app/application/service.py's select_resume(), generate_cover_letter(),
# and generate_answer() currently raise ModuleNotYetAvailableError because
# they depend on app.ai_core, which isn't converted yet.


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="1.0.0",
        debug=settings.DEBUG,
        docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
    app.include_router(integrations_router, prefix=settings.API_V1_PREFIX)
    app.include_router(application_router, prefix=settings.API_V1_PREFIX)
    app.include_router(resume_router, prefix=settings.API_V1_PREFIX)
    # Re-enable email_router as soon as ai_core is converted (see note above
    # this file's imports) — email_comm itself is fully ready.
    # app.include_router(ai_core_router, prefix=settings.API_V1_PREFIX)
    # app.include_router(email_router, prefix=settings.API_V1_PREFIX)

    # app.include_router(notification_router, prefix=settings.API_V1_PREFIX)
    # app.include_router(scheduler_router, prefix=settings.API_V1_PREFIX)
    # app.include_router(reports_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
