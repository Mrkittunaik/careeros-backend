from app.application.enums import STATUS_TRANSITIONS, ApplicationStatusEnum
from app.application.exceptions import InvalidStatusTransitionError


def validate_status_transition(
    from_status: ApplicationStatusEnum, to_status: ApplicationStatusEnum, *, strict: bool = False
) -> None:
    """Recruiting workflows are messy in practice (a company can reject you
    straight out of "draft" if you self-report an outcome, a status can be
    corrected after user error, etc.), so by default any transition is
    permitted and only same-status no-ops are allowed through freely.

    When `strict=True` the caller opts into enforcing STATUS_TRANSITIONS,
    useful for automation surfaces (e.g. an integration that pulls status
    from an ATS) where a bad transition likely indicates a bug.
    """
    if from_status == to_status:
        return
    if not strict:
        return
    allowed = STATUS_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise InvalidStatusTransitionError(from_status.value, to_status.value)


def validate_priority_score_consistency(ai_match_score: float | None) -> None:
    if ai_match_score is not None and not (0 <= ai_match_score <= 100):
        raise ValueError("ai_match_score must be between 0 and 100.")
