"""Service-layer tests for app.resume, run against an in-memory
mongomock-motor database, following the same pattern as
app/autoapply/tests/test_service.py. External systems (object storage,
ChromaDB embeddings, and outbound AI provider HTTP calls, plus the Celery
pipeline trigger) are monkeypatched so these tests exercise ResumeService's
actual control flow -- ownership checks, status transitions, selection-rule
precedence, BYOK key encryption -- without touching the network or a real
MinIO/ChromaDB/Celery broker.
"""

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.resume.exceptions import (
    InvalidFileTypeError,
    InvalidSelectionRuleError,
    NoResumesAvailableError,
    ResumeAccessDeniedError,
    ResumeNotFoundError,
)
from app.resume.models import AIProviderEnum, ResumeStatusEnum
from app.resume.services import ResumeService


@pytest.fixture(autouse=True)
def _patch_external_systems(monkeypatch):
    """Storage/embeddings/celery are not database concerns; stub them so
    tests never touch MinIO, ChromaDB, or a real Celery broker.
    """
    monkeypatch.setattr("app.resume.services.upload_file", lambda *a, **k: None)
    monkeypatch.setattr("app.resume.services.get_presigned_url", lambda *a, **k: "https://storage.example/resume.pdf")
    monkeypatch.setattr("app.resume.services.delete_file", lambda *a, **k: None)
    monkeypatch.setattr("app.resume.services.delete_resume_embedding", lambda *a, **k: None)
    monkeypatch.setattr("app.resume.services.semantic_search", lambda *a, **k: [])
    monkeypatch.setattr("app.resume.services.run_full_resume_pipeline.delay", lambda *a, **k: None)


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["resume_test"]


@pytest.fixture
def service(db) -> ResumeService:
    return ResumeService(db)


# --- Upload ---

@pytest.mark.asyncio
async def test_upload_resume_creates_uploaded_resume(service: ResumeService) -> None:
    resume = await service.upload_resume("user-1", "cv.pdf", b"%PDF-1.4 fake", title=None, tags=["backend"])

    assert resume.status == ResumeStatusEnum.UPLOADED
    assert resume.user_id == "user-1"
    assert resume.title == "cv.pdf"
    assert resume.tags == ["backend"]
    assert resume.version_number == 1


@pytest.mark.asyncio
async def test_upload_resume_rejects_unsupported_extension(service: ResumeService) -> None:
    with pytest.raises(InvalidFileTypeError):
        await service.upload_resume("user-1", "cv.txt", b"hello", title=None, tags=None)


# --- Ownership / CRUD ---

@pytest.mark.asyncio
async def test_get_resume_raises_not_found_for_unknown_id(service: ResumeService) -> None:
    with pytest.raises(ResumeNotFoundError):
        await service.get_resume("user-1", "does-not-exist")


@pytest.mark.asyncio
async def test_get_resume_raises_access_denied_for_wrong_owner(service: ResumeService) -> None:
    resume = await service.upload_resume("user-1", "cv.pdf", b"data", title=None, tags=None)
    with pytest.raises(ResumeAccessDeniedError):
        await service.get_resume("user-2", resume.id)


@pytest.mark.asyncio
async def test_update_resume_applies_only_provided_fields(service: ResumeService) -> None:
    resume = await service.upload_resume("user-1", "cv.pdf", b"data", title="Old Title", tags=None)
    updated = await service.update_resume("user-1", resume.id, title="New Title", tags=None, is_active=None)

    assert updated.title == "New Title"


@pytest.mark.asyncio
async def test_delete_resume_soft_deletes(service: ResumeService) -> None:
    resume = await service.upload_resume("user-1", "cv.pdf", b"data", title=None, tags=None)
    await service.delete_resume("user-1", resume.id)

    with pytest.raises(ResumeNotFoundError):
        await service.get_resume("user-1", resume.id)


# --- Cloning / version chain ---

@pytest.mark.asyncio
async def test_clone_resume_increments_version_and_links_parent(service: ResumeService) -> None:
    original = await service.upload_resume("user-1", "cv.pdf", b"data", title="CV", tags=None)
    clone = await service.clone_resume("user-1", original.id, new_title=None)

    assert clone.version_number == 2
    assert clone.parent_resume_id == original.id
    assert clone.title == "CV v2"


@pytest.mark.asyncio
async def test_version_chain_includes_original_and_clones(service: ResumeService) -> None:
    original = await service.upload_resume("user-1", "cv.pdf", b"data", title="CV", tags=None)
    clone = await service.clone_resume("user-1", original.id, new_title=None)

    chain = await service.get_version_chain("user-1", original.id)
    ids = {r.id for r in chain}
    assert original.id in ids
    assert clone.id in ids


# --- Selection rules ---

@pytest.mark.asyncio
async def test_create_selection_rule_rejects_unowned_resume(service: ResumeService) -> None:
    with pytest.raises(InvalidSelectionRuleError):
        await service.create_selection_rule("user-1", "Backend", "does-not-exist", priority=0)


@pytest.mark.asyncio
async def test_selection_rule_wins_over_ai_ranking(service: ResumeService) -> None:
    resume = await service.upload_resume("user-1", "cv.pdf", b"data", title="CV", tags=None)
    await service.create_selection_rule("user-1", "Backend Engineer", resume.id, priority=10)

    result = await service.select_resume_for_job("user-1", "Backend Engineer", job_description=None)

    assert result["selection_method"] == "rule"
    assert result["selected_resume_id"] == resume.id


@pytest.mark.asyncio
async def test_select_resume_for_job_raises_when_no_resumes(service: ResumeService) -> None:
    with pytest.raises(NoResumesAvailableError):
        await service.select_resume_for_job("user-1", "Backend Engineer", job_description=None)


@pytest.mark.asyncio
async def test_delete_selection_rule_rejects_unowned_rule(service: ResumeService) -> None:
    with pytest.raises(InvalidSelectionRuleError):
        await service.delete_selection_rule("user-1", "does-not-exist")


# --- BYOK AI provider keys ---

@pytest.mark.asyncio
async def test_set_and_list_ai_provider_key_encrypts_at_rest(service: ResumeService) -> None:
    await service.set_ai_provider_key("user-1", AIProviderEnum.GROQ, "sk-test-123")
    keys = await service.list_ai_provider_keys("user-1")

    assert len(keys) == 1
    assert keys[0].provider == AIProviderEnum.GROQ
    assert keys[0].encrypted_api_key != "sk-test-123"  # never stored in plaintext


@pytest.mark.asyncio
async def test_set_ai_provider_key_upserts_existing_provider(service: ResumeService) -> None:
    await service.set_ai_provider_key("user-1", AIProviderEnum.GROQ, "sk-old")
    await service.set_ai_provider_key("user-1", AIProviderEnum.GROQ, "sk-new")

    keys = await service.list_ai_provider_keys("user-1")
    assert len(keys) == 1  # upsert, not a second row


@pytest.mark.asyncio
async def test_delete_ai_provider_key_returns_false_when_absent(service: ResumeService) -> None:
    deleted = await service.delete_ai_provider_key("user-1", AIProviderEnum.OPENAI)
    assert deleted is False


# --- Search ---

@pytest.mark.asyncio
async def test_search_resumes_filters_by_min_ats_score(service: ResumeService) -> None:
    resume = await service.upload_resume("user-1", "cv.pdf", b"data", title="CV", tags=None)
    await service.repo.update_fields(resume.id, ats_score=40)

    results = await service.search_resumes(
        "user-1", query=None, skill=None, job_role=None, min_ats_score=80, semantic=False, limit=10
    )
    assert results == []
