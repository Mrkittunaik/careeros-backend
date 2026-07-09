from app.application.enums import ApplicationStatusEnum

# Note: the actual prompt text for APPLICATION_ANSWER_PROMPT_KEY lives in
# app.ai_core.prompts._DEFAULTS (the single source of truth for all AI
# Engine prompts per Part 4's architecture), not here. This module only
# holds application-specific helpers that don't belong in ai_core.


def compute_package_completeness(*, has_resume: bool, has_cover_letter: bool, attachment_count: int) -> tuple[bool, list[str]]:
    """Determines whether an application package is ready to be marked
    'Ready'/'Submitted' and what's missing if not.
    """
    missing: list[str] = []
    if not has_resume:
        missing.append("resume")
    if not has_cover_letter:
        missing.append("cover_letter")
    return (len(missing) == 0), missing


def next_status_hint(current: ApplicationStatusEnum) -> list[ApplicationStatusEnum]:
    from app.application.enums import STATUS_TRANSITIONS

    return sorted(STATUS_TRANSITIONS.get(current, frozenset()), key=lambda s: s.value)
