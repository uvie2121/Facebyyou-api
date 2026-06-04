"""Authentication endpoints.

In production, login/signup is handled by AWS Cognito (hosted UI or SDK) and the
mobile app sends Cognito-issued JWTs. The `/auth/dev-login` route exists ONLY in
non-production environments to let engineers obtain a token quickly.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.core.security import create_access_token
from app.models.schemas import DevLoginRequest, Token

router = APIRouter()


@router.post("/dev-login", response_model=Token, summary="Issue a local dev token")
async def dev_login(payload: DevLoginRequest) -> Token:
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not available in production",
        )
    user_id = payload.user_id or f"dev-{uuid.uuid4().hex[:12]}"
    token = create_access_token(subject=user_id, extra_claims={"email": payload.email})
    return Token(access_token=token)
