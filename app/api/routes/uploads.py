"""Upload endpoints: hand the client presigned S3 POST forms."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.security import get_current_user
from app.models.schemas import (
    SessionCreateRequest,
    SessionResponse,
    SessionUploadUrlResponse,
    TokenPayload,
    ValidationRequest,
)
from app.services import database, storage
from app.services.face_analysis import fetch_image_from_s3
from app.services.image_validation import validate_image

router = APIRouter()


@router.post("/{session_id}/validate")
async def validate_upload(
    session_id: str,
    payload: ValidationRequest,
    current: TokenPayload = Depends(get_current_user),
):
    """Provides instant validation feedback for a single uploaded image."""
    try:
        # Fetch the newly uploaded image from S3
        session = database.get_session(session_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        if session.get("user_id") != current.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Session does not belong to user"
            )
        if session.get("status") != "OPEN":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session is not open")
        object_key = f"{storage._get_session_base_path(current.sub, session_id)}/{payload.view}.jpg"
        storage.validate_uploaded_jpeg(object_key)
        image_array = fetch_image_from_s3(object_key)

        # Run the existing strict validation logic
        result = validate_image(image_array, payload.view)

        # Return exact API Spec format
        return result

    except HTTPException:
        raise
    except Exception:
        return {"success": False, "valid": False, "errors": ["Image validation failed"]}


@router.post("/{session_id}/uploads", response_model=SessionResponse)
async def upload_session(
    session_id: str,
    payload: SessionCreateRequest,
    current: TokenPayload = Depends(get_current_user),
):
    existing_session = database.get_session(session_id)
    if existing_session and existing_session.get("user_id") != current.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Session does not belong to user"
        )
    if existing_session and existing_session.get("status") != "OPEN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session is not open")
    if not existing_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    urls = storage.create_session_presigned_urls(
        user_id=current.sub,
        session_id=session_id,
        content_type=payload.content_type,
        files_map=payload.files,
    )
    # Return three presigned POST forms, one for each required view.
    return {"session_id": session_id, "status": "OPEN", "urls": urls}


@router.post("/{session_id}/uploads/{view}", response_model=SessionUploadUrlResponse)
async def refresh_upload_url(
    session_id: str,
    view: str,
    current: TokenPayload = Depends(get_current_user),
) -> SessionUploadUrlResponse:
    """Refresh one expired or failed POST form without invalidating the other views."""
    existing_session = database.get_session(session_id)
    if not existing_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if existing_session.get("user_id") != current.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Session does not belong to user"
        )
    if existing_session.get("status") != "OPEN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session is not open")

    upload = storage.create_session_presigned_url(
        user_id=current.sub,
        session_id=session_id,
        view=view,
    )
    return SessionUploadUrlResponse(
        session_id=session_id,
        view=view,
        upload_url=upload["url"],
        upload_fields=upload["fields"],
        expires_in=settings.S3_PRESIGNED_URL_TTL_SECONDS,
    )
