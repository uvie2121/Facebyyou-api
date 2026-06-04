"""Upload endpoints: hand the client a presigned S3 POST."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.schemas import (
    PresignUploadRequest,
    PresignUploadResponse,
    TokenPayload,
)
from app.services import storage

router = APIRouter()


@router.post(
    "/presign",
    response_model=PresignUploadResponse,
    summary="Get a presigned URL to upload a face image/video to S3",
)
async def presign_upload(
    payload: PresignUploadRequest,
    current: TokenPayload = Depends(get_current_user),
) -> PresignUploadResponse:
    return storage.create_presigned_upload(
        user_id=current.sub,
        filename=payload.filename,
        content_type=payload.content_type,
    )
