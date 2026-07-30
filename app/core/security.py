"""Authentication helpers.

For the MVP we support JWT bearer tokens. Tokens are normally minted by AWS
Cognito (or Firebase Auth); this module verifies them and exposes the current
user identity to route handlers. A local HS256 path exists for development so
engineers can work without standing up Cognito.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth

from app.core.config import settings
from app.models.schemas import TokenPayload

_bearer = HTTPBearer(auto_error=False)


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Mint a local development JWT (HS256). Not used when Firebase is configured."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iss": "facebyyou-local",
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str) -> TokenPayload:
    try:
        # verification against the user pool's well-known keys.
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from exc

    subject = payload.get("sub")
    role = payload.get("role")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )
    return TokenPayload(sub=subject, email=payload.get("email"), role=role, claims=payload)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TokenPayload:
    """
    FastAPI dependency that resolves the authenticated user from a bearer token.
    Supports BOTH Firebase production tokens and local Dev tokens.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or not credentials.credentials:
        raise credentials_exception
    token = credentials.credentials

    # Try Firebase (Production Flow)
    try:
        decoded_token = firebase_auth.verify_id_token(token)
        return TokenPayload(sub=decoded_token["uid"], email=decoded_token.get("email", ""))
    except Exception:
        # If Firebase rejects it, try the Local Dev Token flow
        try:
            return _decode_token(token)

        except Exception as local_error:
            # If BOTH fail, the token is truly invalid or expired
            raise credentials_exception from local_error
