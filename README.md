# CareerOS AI — Backend

Production-grade modular monolith backend (Clean Architecture + DDD) for an AI-powered
career/job-application automation platform.

**Stack:** Python 3.13, FastAPI, SQLAlchemy 2.x (async), Alembic, Celery + Celery Beat,
Redis, PostgreSQL, Playwright, ChromaDB, MinIO.

## What's implemented in this drop

- `app/core/` — settings, async DB engine/base model, JWT + AES-256-GCM security utils,
  structured JSON logging with request-ID propagation, global exception handlers, Celery app
  with per-domain queues (`default`, `ai`, `automation`, `email`, `resume`, `job`, `application`).
- `app/auth/` — full module: models (User, UserDevice, OAuthAccount, RefreshToken,
  UserActivityLog), repositories, services (register/login/refresh-rotation/logout/logout-all),
  router (`/api/v1/auth/*`), RBAC + PBAC dependency guards, Celery tasks (token purge, async
  activity logging).
- `app/health/` — `/health`, `/liveness`, `/readiness` (checks DB connectivity).
- Alembic wired to the async engine and `Base.metadata` (autogenerate-ready).
- Docker: multi-stage Dockerfiles for API, Celery workers, and the Playwright automation
  worker; `docker-compose.yml` wiring Postgres, Redis, MinIO, ChromaDB, NGINX (SSL + WS
  upgrade + rate limiting), and per-queue Celery workers + Beat.
- GitHub Actions CI: Ruff, Black, Alembic migration check, Pytest — against live Postgres/Redis
  service containers.

- `app/resume/` — full Resume Intelligence System: models (Resume w/ versioning chain,
  ResumeAIAnalysis, ResumeATSReport, ResumeJobMatch, ResumeSelectionRule/Log,
  UserAIProviderKey), repositories, AI provider manager (Groq/OpenAI/Gemini/Claude/Ollama
  with automatic fallback, **BYOK** — users can save their own encrypted API key per
  provider via `/api/v1/resumes/ai-keys`, falling back to platform keys if unset), parsing
  engine (pypdf/python-docx + regex hints), AI resume engine (structured extraction,
  classification, ATS scoring, job matching, optimization — never fabricates experience),
  embeddings (ChromaDB, per-user scoped semantic search), resume selection engine
  (user rules first, AI ranking fallback weighted by match % / ATS score / past success
  rate), object storage (MinIO, private per-user keys), Celery pipeline
  (`upload -> parse -> AI analyze -> ATS score -> embed`, dedicated `resume` queue), router
  (`/api/v1/resumes/*`, full spec surface).

## Not yet implemented (scaffolded as commented-out router includes / task modules)

Job & Application Engine, Automation Hub, Email Communication, Analytics —
each follows the exact same `router/services/repositories/models/schemas/exceptions/tasks`
layout as `app/auth/` and `app/resume/`. Tell me which module to build next and I'll
generate it in full.

## Local setup

```bash
cp .env.example .env        # fill in real secrets
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start infra
docker compose up -d db redis minio chromadb

# Run migrations
alembic revision --autogenerate -m "init auth schema"
alembic upgrade head

# Run API
uvicorn app.main:app --reload

# Run a worker (separate terminal)
celery -A app.core.celery_app.celery_app worker --loglevel=INFO --queues=default,ai,resume,job,application

# Run beat (separate terminal)
celery -A app.core.celery_app.celery_app beat --loglevel=INFO
```

Full stack via Docker:

```bash
docker compose up --build
```

## Auth endpoints

| Method | Path                         | Description                          |
|--------|------------------------------|---------------------------------------|
| POST   | `/api/v1/auth/register`      | Create a new user                    |
| POST   | `/api/v1/auth/login`         | Password login, issues token pair    |
| POST   | `/api/v1/auth/refresh`       | Rotates refresh token                |
| POST   | `/api/v1/auth/logout`        | Revokes a single refresh token       |
| POST   | `/api/v1/auth/logout-all`    | Revokes all sessions for the user    |
| GET    | `/api/v1/auth/me`            | Current authenticated user           |

RBAC/PBAC: use `Depends(RequireRole(RoleEnum.ADMIN))` or
`Depends(RequirePermission("resume:delete"))` on any route.

## Resume endpoints

| Method | Path                                   | Description                                    |
|--------|-----------------------------------------|-------------------------------------------------|
| POST   | `/api/v1/resumes/upload`                | Upload PDF/DOCX, triggers async parse pipeline  |
| GET    | `/api/v1/resumes/list`                  | List resumes (filter by tag/status, paginated)  |
| GET    | `/api/v1/resumes/{id}`                  | Get single resume                               |
| PUT    | `/api/v1/resumes/{id}`                  | Update title/tags/active flag                   |
| DELETE | `/api/v1/resumes/{id}`                  | Soft-delete + purge storage/embedding           |
| POST   | `/api/v1/resumes/{id}/clone`            | Clone as new version                            |
| GET    | `/api/v1/resumes/{id}/versions`         | Full version chain                              |
| POST   | `/api/v1/resumes/{id}/parse`            | Force re-parse (sync)                           |
| POST   | `/api/v1/resumes/{id}/ats-score`        | Score against optional job description          |
| POST   | `/api/v1/resumes/{id}/match-job`        | Match against a job description                 |
| POST   | `/api/v1/resumes/{id}/optimize`         | AI rewrite/ATS-keyword suggestions              |
| POST   | `/api/v1/resumes/select-for-job`        | Resume Selection Engine (rules -> AI ranking)   |
| GET/POST/DELETE | `/api/v1/resumes/rules`        | User-defined selection rules CRUD               |
| POST   | `/api/v1/resumes/search`                | Filter or semantic (ChromaDB) search            |
| GET/PUT/DELETE | `/api/v1/resumes/ai-keys/*`      | BYOK: save/list/remove your own AI provider key |

## Generating the first migration

This sandbox has no live Postgres, so the initial migration wasn't generated here. Once you
have Postgres running (`docker compose up -d db`), run:

```bash
alembic revision --autogenerate -m "init auth + resume schema"
alembic upgrade head
```

`alembic/env.py` already imports both `app.auth.models` and `app.resume.models`, so
autogenerate will pick up all 8 new resume tables in one pass.
