"""Analysis endpoints: trigger face analysis and fetch results/history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.models.schemas import (
    AnalysisRequest,
    AnalysisResult,
    TokenPayload,
)
from app.services import database, face_analysis, storage

router = APIRouter()


@router.post(
    "/{session_id}",
    response_model=AnalysisResult,
    status_code=status.HTTP_201_CREATED,
    summary="Run tri-angle face analysis on previously uploaded objects.",
)
async def create_analysis(
    session_id: str,
    payload: AnalysisRequest,
    current: TokenPayload = Depends(get_current_user),
) -> AnalysisResult:
    existing_session = database.get_session(session_id)
    if not existing_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if existing_session.get("user_id") != current.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Session does not belong to user"
        )
    if existing_session.get("status") != "OPEN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session is not open")

    base_path = storage._get_session_base_path(current.sub, session_id)

    # Predict the exact keys based on how they were named in the upload step.
    front_key = f"{base_path}/front.jpg"
    left_key = f"{base_path}/left.jpg"
    right_key = f"{base_path}/right.jpg"

    # Validate all three views landed safely in S3
    for key in [front_key, left_key, right_key]:
        storage.validate_uploaded_jpeg(key)

    # Fetch, process, and aggregate the 3 views
    result = await face_analysis.analyze(
        user_id=current.sub,
        session_id=session_id,
        front_key=front_key,
        left_key=left_key,
        right_key=right_key,
        analysis_types=payload.analysis_types,
    )

    for view_name, key in [("front", front_key), ("left", left_key), ("right", right_key)]:
        database.log_uploaded_image(
            user_id=current.sub, session_id=session_id, image_url=key, image_type=view_name
        )

    saved_result = database.save_analysis(result)

    # Lock only after a durable analysis result exists.
    database.update_session_status(current.sub, session_id, "LOCKED")

    return saved_result


@router.get(
    "",
    response_model=list[AnalysisResult],
    summary="List the current user's analysis history",
)
async def list_analyses(
    limit: int = 25,
    current: TokenPayload = Depends(get_current_user),
) -> list[AnalysisResult]:
    return database.list_analyses(current.sub, limit=limit)


@router.get("/session/{session_id}", response_model=list[AnalysisResult])
async def get_session_history(session_id: str, current: TokenPayload = Depends(get_current_user)):
    results = database.get_analyses_by_session(user_id=current.sub, session_id=session_id)
    return results


@router.get(
    "/{analysis_id}",
    response_model=AnalysisResult,
    summary="Fetch a single analysis result",
)
async def get_analysis(
    analysis_id: str,
    current: TokenPayload = Depends(get_current_user),
) -> AnalysisResult:
    result = database.get_analysis(current.sub, analysis_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found",
        )
    return result
