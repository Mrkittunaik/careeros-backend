import pytest

from app.application.enums import ApplicationStatusEnum, TERMINAL_STATUSES
from app.application.exceptions import InvalidStatusTransitionError
from app.application.validators import validate_status_transition


def test_same_status_transition_always_allowed() -> None:
    validate_status_transition(ApplicationStatusEnum.DRAFT, ApplicationStatusEnum.DRAFT, strict=True)


def test_non_strict_mode_allows_any_transition() -> None:
    # Non-strict (default) mode permits jumping straight from draft to
    # offer, since recruiting outcomes can be self-reported out of order.
    validate_status_transition(ApplicationStatusEnum.DRAFT, ApplicationStatusEnum.OFFER, strict=False)


def test_strict_mode_allows_defined_transition() -> None:
    validate_status_transition(ApplicationStatusEnum.DRAFT, ApplicationStatusEnum.PREPARED, strict=True)


def test_strict_mode_rejects_undefined_transition() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition(ApplicationStatusEnum.DRAFT, ApplicationStatusEnum.OFFER, strict=True)


def test_terminal_statuses_have_no_outgoing_transitions_except_archived() -> None:
    from app.application.enums import STATUS_TRANSITIONS

    # ARCHIVED is the only true dead-end. ACCEPTED can still move to
    # CLOSED (the "offer accepted, role now closed out") and every other
    # terminal status can move only to ARCHIVED.
    assert STATUS_TRANSITIONS[ApplicationStatusEnum.ARCHIVED] == frozenset()
    assert STATUS_TRANSITIONS[ApplicationStatusEnum.ACCEPTED] == {ApplicationStatusEnum.CLOSED}
    for status in TERMINAL_STATUSES - {ApplicationStatusEnum.ARCHIVED, ApplicationStatusEnum.ACCEPTED}:
        assert STATUS_TRANSITIONS[status] <= {ApplicationStatusEnum.ARCHIVED}


def test_all_status_values_present_in_transition_map() -> None:
    from app.application.enums import STATUS_TRANSITIONS

    for status in ApplicationStatusEnum:
        assert status in STATUS_TRANSITIONS
