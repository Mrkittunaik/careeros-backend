"""Object storage service for resume files (MinIO/S3-compatible).

Files are stored under a per-user prefix (`{user_id}/{resume_id}/{filename}`)
so cross-user access is structurally prevented at the key level, in addition
to the DB-level ownership checks enforced in the service layer.
"""

import io
import logging
import uuid
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger("app.resume.storage")

_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        if not _client.bucket_exists(settings.MINIO_BUCKET_RESUMES):
            _client.make_bucket(settings.MINIO_BUCKET_RESUMES)
    return _client


def build_storage_key(user_id: uuid.UUID, resume_id: uuid.UUID, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"{user_id}/{resume_id}/{safe_name}"


def upload_file(storage_key: str, file_bytes: bytes, content_type: str) -> str:
    """Uploads bytes to object storage and returns the storage key.
    File is private by default (no public ACL); access via presigned URLs.
    """
    client = get_minio_client()
    try:
        client.put_object(
            settings.MINIO_BUCKET_RESUMES,
            storage_key,
            data=io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type,
        )
        return storage_key
    except S3Error:
        logger.exception("resume_upload_failed", extra={"storage_key": storage_key})
        raise


def get_presigned_url(storage_key: str, expires_minutes: int = 60) -> str:
    client = get_minio_client()
    return client.presigned_get_object(
        settings.MINIO_BUCKET_RESUMES, storage_key, expires=timedelta(minutes=expires_minutes)
    )


def download_file(storage_key: str) -> bytes:
    client = get_minio_client()
    response = client.get_object(settings.MINIO_BUCKET_RESUMES, storage_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_file(storage_key: str) -> None:
    client = get_minio_client()
    try:
        client.remove_object(settings.MINIO_BUCKET_RESUMES, storage_key)
    except S3Error:
        logger.exception("resume_delete_failed", extra={"storage_key": storage_key})
