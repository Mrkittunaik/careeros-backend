# Part 5A — Application Management Engine

`app/application/` — job application lifecycle management, integrating the
Resume Engine (Part 3) and AI Core Engine (Part 4) into a single package
per application.

## What this module owns

| Table | Purpose |
|---|---|
| `applications` | Core application record: company/role, status, priority, package links (resume, cover letter, match result), package metadata (portfolio/github/linkedin/website URLs), timestamps. |
| `application_timeline_events` | Append-only audit log. Every status change and most mutations write one of these. |
| `application_resume_history` | Every resume ever attached to an application, not just the current one — answers "resume version history". |
| `application_answers` | Q&A pairs for application-form questions, AI-generated or manual. |
| `application_attachments` | Portfolio / GitHub / LinkedIn / website / other links beyond the four primary URL columns on `applications`. |

## Integration points

- **Resume Engine (Part 3)**: `ApplicationService.select_resume` delegates
  AI-based auto-selection to the existing `ResumeService.select_resume_for_job`
  rather than reimplementing selection logic. Resumes are referenced by
  `resume_id`, never copied.
- **AI Core Engine (Part 4)**: `ApplicationService.generate_cover_letter`
  delegates to `AICoreService.generate_cover_letter` (existing
  `CoverLetterEngine`). AI answer generation dispatches through the existing
  `AIRouter.dispatch_json`, the same single entry point every other AI Core
  sub-system uses, with a new prompt key (`application_answer_prompt`)
  registered in `app.ai_core.prompts._DEFAULTS` — the one small, justified
  edit to an existing Part 4 file, since that dict is the documented single
  source of truth for all AI Engine prompts.
- **Auth**: all endpoints require `get_current_active_user`; every query is
  scoped to `user_id` via `ApplicationRepository.get_owned` /
  `_get_owned_or_raise`.
- **Celery**: `app.application.tasks` registered in `celery_app.py`'s
  `include` list. The `application` queue routing already existed in
  `task_routes` (reserved ahead of time in Part 4's setup) — no change
  needed there.

## Status lifecycle

`draft -> prepared -> ready -> submitted -> applied -> viewed -> under_review
-> assessment -> interview -> offer -> accepted -> closed`, with
`rejected` / `withdrawn` / `archived` as off-ramps at multiple points.

By default, transitions are **not strictly enforced** — real recruiting
processes skip states, get corrected after user error, or get self-reported
out of order. Pass `strict_transition: true` on `PUT
/applications/{id}/status` to enforce `STATUS_TRANSITIONS` from
`enums.py`, useful for automated integrations where an unexpected jump
likely indicates a bug rather than real-world messiness.

Every transition — strict or not — writes an `ApplicationTimelineEvent`.

## Events

`app/application/events.py` is a small in-process pub/sub, deliberately
minimal since no project-wide event bus exists yet in Parts 1-4. It's
structured so it can be swapped for a shared bus later without touching
call sites in `service.py`. Handlers are best-effort: an exception in a
handler is logged and swallowed, never breaks the primary transaction.

## API surface

All under `/api/v1/applications`, see `router.py` for the full list —
CRUD, search/filter/sort/paginate, status updates + timeline, resume
selection + history, cover letter generation, AI answer generation +
manual answers, attachments, and package builder (`GET
/applications/{id}/package`, which also assembles a `is_complete` /
`missing_items` readiness check).

## Tests

`tests/` covers status-transition validation, package-completeness logic,
and core service flows (create, get with ownership checks, status
transitions incl. `applied_at`/`closed_at` side effects) against
lightweight in-memory fakes — no live Postgres dependency, matching the
fact that no DB test fixture infrastructure exists yet elsewhere in the
project (`tests/test_health.py` is the only prior precedent and doesn't
touch the DB either).
