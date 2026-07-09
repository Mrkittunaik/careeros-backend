from app.application.enums import ApplicationStatusEnum
from app.application.utils import compute_package_completeness, next_status_hint


def test_package_incomplete_without_resume() -> None:
    is_complete, missing = compute_package_completeness(
        has_resume=False, has_cover_letter=True, attachment_count=0
    )
    assert not is_complete
    assert "resume" in missing


def test_package_incomplete_without_cover_letter() -> None:
    is_complete, missing = compute_package_completeness(
        has_resume=True, has_cover_letter=False, attachment_count=0
    )
    assert not is_complete
    assert "cover_letter" in missing


def test_package_complete_with_resume_and_cover_letter() -> None:
    is_complete, missing = compute_package_completeness(
        has_resume=True, has_cover_letter=True, attachment_count=0
    )
    assert is_complete
    assert missing == []


def test_next_status_hint_for_draft() -> None:
    hints = next_status_hint(ApplicationStatusEnum.DRAFT)
    assert ApplicationStatusEnum.PREPARED in hints


def test_next_status_hint_for_archived_is_empty() -> None:
    assert next_status_hint(ApplicationStatusEnum.ARCHIVED) == []
