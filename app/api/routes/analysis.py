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
    "",
    response_model=AnalysisResult,
    status_code=status.HTTP_201_CREATED,
    summary="Run face analysis on a previously uploaded object",
)
async def create_analysis(
    payload: AnalysisRequest,
    current: TokenPayload = Depends(get_current_user),
) -> AnalysisResult:
    if not storage.object_exists(payload.object_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uploaded object not found. Complete the upload first.",
        )
    result = face_analysis.analyze(
        user_id=current.sub,
        object_key=payload.object_key,
        analysis_types=payload.analysis_types,
    )
    return database.save_analysis(result)


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
