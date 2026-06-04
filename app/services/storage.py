"""S3-backed storage for user-uploaded face images and videos.

We hand the mobile client a presigned POST so the large media payload uploads
directly to S3, never transiting the API server. This keeps the EC2 box light
and lets us enforce size/content-type limits via the presigned policy.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from botocore.exceptions import ClientError
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import PresignUploadResponse
from app.services.aws import s3_client

logger = get_logger(__name__)


def _build_object_key(user_id: str, filename: str) -> str:
    """Namespace uploads by user and date for easy lifecycle management."""
    today = datetime.now(UTC).strftime("%Y/%m/%d")
    safe_name = filename.replace("/", "_").strip() or "upload"
    return f"uploads/{user_id}/{today}/{uuid.uuid4().hex}_{safe_name}"


def create_presigned_upload(
    *, user_id: str, filename: str, content_type: str
) -> PresignUploadResponse:
    """Generate a presigned POST that constrains content-type and size."""
    if content_type not in settings.ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type: {content_type}",
        )

    object_key = _build_object_key(user_id, filename)
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    try:
        presigned = s3_client().generate_presigned_post(
            Bucket=settings.S3_UPLOAD_BUCKET,
            Key=object_key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=settings.S3_PRESIGNED_URL_TTL_SECONDS,
        )
    except ClientError as exc:
        logger.error("Failed to create presigned upload", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not create upload URL",
        ) from exc

    return PresignUploadResponse(
        upload_id=uuid.uuid4().hex,
        object_key=object_key,
        upload_url=presigned["url"],
        fields=presigned["fields"],
        expires_in=settings.S3_PRESIGNED_URL_TTL_SECONDS,
    )


def object_exists(object_key: str) -> bool:
    """Confirm an upload landed in S3 before we kick off analysis."""
    try:
        s3_client().head_object(Bucket=settings.S3_UPLOAD_BUCKET, Key=object_key)
        return True
    except ClientError:
        return False
