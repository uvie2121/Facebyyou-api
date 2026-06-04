"""User profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.models.schemas import TokenPayload, UserProfile
from app.services import database

router = APIRouter()


@router.get("/me", response_model=UserProfile, summary="Get current user profile")
async def get_me(current: TokenPayload = Depends(get_current_user)) -> UserProfile:
    existing = database.get_user(current.sub)
    if existing:
        return existing
    # First-seen user: return a lightweight profile from token claims.
    return UserProfile(user_id=current.sub, email=current.email)


@router.put("/me", response_model=UserProfile, summary="Create or update profile")
async def update_me(
    profile: UserProfile,
    current: TokenPayload = Depends(get_current_user),
) -> UserProfile:
    if profile.user_id != current.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify another user's profile",
        )
    return database.upsert_user(profile)
