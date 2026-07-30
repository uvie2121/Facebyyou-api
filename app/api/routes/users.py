"""User profile endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.models.schemas import TokenPayload, UserProfile, UserProfileUpdate
from app.services import database

router = APIRouter()


@router.get("/me", response_model=UserProfile, summary="Get current user profile")
async def get_me(current: TokenPayload = Depends(get_current_user)) -> UserProfile:
    existing = database.get_user(current.sub)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found in database. Please register.",
        )

    return existing

    # First-seen user: return a lightweight profile from token claims.
    # return UserProfile(user_id=current.sub, email=current.email)


@router.put("/me", response_model=UserProfile, summary="Update profile")
async def update_me(
    update_data: UserProfileUpdate,  # INPUT: Only accept the restricted, editable fields
    current: TokenPayload = Depends(get_current_user),
) -> UserProfile:  # OUTPUT: Return the fully updated profile
    # Implicitly trust the token for the ID, so no user-provided ID check is needed
    user_id = current.sub

    # Fetch the user's current data from DynamoDB
    existing_user = database.get_user(user_id)
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Merge the new data into the existing profile
    # exclude_unset=True ensures only fields the user actually passed in the PUT request overwrites the existing data. 
    updated_profile = existing_user.model_copy(update=update_data.model_dump(exclude_unset=True))

    # Save the merged profile and return it
    return database.upsert_user(updated_profile)


@router.delete("/me")
async def delete_profile(current_user: TokenPayload = Depends(get_current_user)):
    """Schedule a user-requested account deletion after the 30-day retention window."""
    try:
        deletion_scheduled_at = datetime.now(UTC) + timedelta(days=30)
        database.update_user_status(
            user_id=current_user.sub,
            status="PENDING_DELETION",
            deletion_scheduled_at=deletion_scheduled_at.isoformat(),
        )
        return {
            "success": True,
            "message": "Account scheduled for permanent deletion",
            "deletion_scheduled_at": deletion_scheduled_at.isoformat(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to schedule account deletion.") from exc
