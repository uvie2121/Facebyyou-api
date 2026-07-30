"""S3-backed storage for user-uploaded face images.

Clients upload directly to S3 using presigned POST forms. Their policies enforce
the JPEG content type and size range before S3 accepts an object.
"""

from __future__ import annotations

from datetime import UTC, datetime

from botocore.exceptions import ClientError
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger
from app.services.aws import s3_client

logger = get_logger(__name__)
SESSION_VIEWS = frozenset({"front", "left", "right"})


def _get_session_base_path(user_id: str, session_id: str) -> str:
    """Helper for path logic"""
    today = datetime.now(UTC).strftime("%Y/%m/%d")
    return f"uploads/{user_id}/{today}/{session_id}"


def create_session_presigned_urls(
    user_id: str, session_id: str, content_type: str, files_map: dict[str, str]
) -> dict[str, dict[str, str]]:
    """Generate one canonical, size-limited JPEG POST form per scan view."""

    # 1. Enforce content-type security
    if content_type not in settings.ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type: {content_type}",
        )

    if content_type != "image/jpeg":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Tri-angle analysis sessions currently require image/jpeg uploads",
        )

    if set(files_map) != SESSION_VIEWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Session uploads must contain exactly: front, left, right",
        )

    urls = {}
    for view in SESSION_VIEWS:
        urls[view] = create_session_presigned_url(
            user_id=user_id,
            session_id=session_id,
            view=view,
            content_type=content_type,
        )
    return urls


def create_session_presigned_url(
    *, user_id: str, session_id: str, view: str, content_type: str = "image/jpeg"
) -> dict[str, dict[str, str] | str]:
    """Generate or refresh one canonical, size-limited S3 POST form."""
    if view not in SESSION_VIEWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid scan view"
        )
    if content_type != "image/jpeg":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Tri-angle analysis sessions currently require image/jpeg uploads",
        )
    key = f"{_get_session_base_path(user_id, session_id)}/{view}.jpg"
    try:
        post = s3_client().generate_presigned_post(
            Bucket=settings.S3_UPLOAD_BUCKET,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024],
            ],
            ExpiresIn=settings.S3_PRESIGNED_URL_TTL_SECONDS,
        )
        return {"url": post["url"], "fields": post["fields"]}
    except ClientError as exc:
        logger.error("Failed to generate session upload URL", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate upload URL for this session",
        ) from exc


def create_presigned_read_url(object_key: str) -> str:
    """Give the feedback provider temporary, read-only access to a private image."""
    try:
        return s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_UPLOAD_BUCKET, "Key": object_key},
            ExpiresIn=settings.NIM_IMAGE_URL_TTL_SECONDS,
        )
    except ClientError as exc:
        logger.error("Failed to create temporary image read URL", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not prepare image for analysis",
        ) from exc


def object_exists(object_key: str) -> bool:
    """Confirm an upload landed in S3 before we kick off analysis."""
    try:
        s3_client().head_object(Bucket=settings.S3_UPLOAD_BUCKET, Key=object_key)
        return True
    except ClientError:
        return False


def validate_uploaded_jpeg(object_key: str) -> None:
    """Enforce the scan-upload contract after S3 receives a direct POST."""
    try:
        metadata = s3_client().head_object(Bucket=settings.S3_UPLOAD_BUCKET, Key=object_key)
    except ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded image not found"
        ) from exc

    size = metadata.get("ContentLength", 0)
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if size < 1 or size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image must be no larger than {settings.MAX_UPLOAD_SIZE_MB} MB",
        )
    if metadata.get("ContentType", "").split(";", 1)[0].lower() != "image/jpeg":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Tri-angle analysis sessions require image/jpeg uploads",
        )
