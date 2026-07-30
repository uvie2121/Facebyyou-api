from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.models.schemas import TokenPayload
from app.services import database

router = APIRouter()


@router.get("/trends", summary="Get user improvement trends")
async def get_user_trends(current_user: TokenPayload = Depends(get_current_user)) -> dict[str, Any]:
    """
    Returns lifetime stats from the user profile alongside category-specific
    improvement deltas calculated from the two most recent scans.
    """
    # Fetch the user's lifetime stats directly from their profile
    user = database.get_user(current_user.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Extract the overall metrics (defaulting to 0.0 if no scans exist yet)
    avg_score = float(getattr(user, "average_score", 0.0))
    best_score = float(getattr(user, "best_score", 0.0))
    latest_score = float(getattr(user, "latest_score", 0.0))
    previous_score = float(getattr(user, "previous_score", 0.0))

    # Calculate the overall improvement delta
    overall_improvement = round(latest_score - previous_score, 2) if latest_score else 0.0

    # Fetch a user's two most recent scans to calculate the specific category deltas
    recent_scans = database.list_analyses(current_user.sub, limit=2)

    # Default category deltas if user hasn't done enough scans to compare
    category_deltas = {
        "foundation": 0.0,
        "blend": 0.0,
        "contour": 0.0,
        "eyes": 0.0,
        "lips": 0.0,
        "symmetry": 0.0,
        "baseFinish": 0.0,
        "colorBalance": 0.0,
    }

    # If a user has at least 2 scans, calculate the exact metric improvements
    if len(recent_scans) >= 2:
        latest_scan = recent_scans[0]
        previous_scan = recent_scans[1]

        latest = latest_scan.category_scores
        previous = previous_scan.category_scores
        category_deltas = {
            "foundation": round(latest.foundation_score - previous.foundation_score, 2),
            "blend": round(latest.blend_score - previous.blend_score, 2),
            "contour": round(latest.contour_score - previous.contour_score, 2),
            "eyes": round(latest.eyes_score - previous.eyes_score, 2),
            "lips": round(latest.lips_score - previous.lips_score, 2),
            "symmetry": round(latest.symmetry_score - previous.symmetry_score, 2),
            "baseFinish": round(latest.base_finish_score - previous.base_finish_score, 2),
            "colorBalance": round(latest.color_balance_score - previous.color_balance_score, 2),
        }

    # Return the expanded JSON payload for the frontend dashboard
    return {
        "averageScore": avg_score,
        "bestScore": best_score,
        "previousScore": previous_score,
        "latestScore": latest_score,
        "improvement": overall_improvement,
        "categories": category_deltas,
    }
