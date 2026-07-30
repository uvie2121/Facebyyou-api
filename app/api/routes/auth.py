"""Authentication endpoints.

In production, login/signup is handled by Firebase and the
mobile app sends Firebase-issued JWTs. The `/auth/dev-login` route exists ONLY in
non-production environments to let engineers obtain a token quickly for dev.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
from fastapi import APIRouter, HTTPException, status
from firebase_admin import auth as firebase_auth

from app.core.config import settings
from app.core.security import create_access_token
from app.models.schemas import (
    DevLoginRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SocialAuthRequest,
    Token,
    UserProfile,
)
from app.services import database

router = APIRouter()


@router.post("/dev-login", response_model=Token, summary="Issue a local dev token")
async def dev_login(payload: DevLoginRequest) -> Token:
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not available in production",
        )
    user_id = payload.user_id or f"dev-{uuid.uuid4().hex[:12]}"
    email = payload.email

    existing_user = database.get_user(user_id)
    if not existing_user:
        mock_profile = UserProfile(
            user_id=user_id,
            email=email,
            display_name="Dev Test User",
            skin_type="Combination",
            total_scans=0,
            average_score=Decimal("0.0"),
        )
        database.upsert_user(mock_profile)

    token = create_access_token(
        subject=user_id, extra_claims={"email": payload.email, "role": "USER"}
    )
    return Token(access_token=token)


async def _firebase_rest_call(endpoint: str, payload: dict) -> dict:
    """Helper to communicate with Firebase Auth REST API for Email/Password ops."""
    FIREBASE_REST_URL = "https://identitytoolkit.googleapis.com/v1/accounts"

    url = f"{FIREBASE_REST_URL}:{endpoint}?key={settings.FIREBASE_WEB_API_KEY}"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        data = response.json()
        if response.status_code != 200:
            error_msg = data.get("error", {}).get("message", "Authentication failed")
            raise HTTPException(status_code=400, detail=error_msg)
        return data


@router.post("/register", summary="Create user account with Email")
async def register_user(payload: RegisterRequest):
    try:
        # Create the user securely in Firebase
        display_name = f"{payload.firstName} {payload.lastName}"
        user_record = firebase_auth.create_user(
            email=payload.email, password=payload.password, display_name=display_name
        )

        # Immediately create their blank profile in DynamoDB
        new_profile = UserProfile(
            user_id=user_record.uid,
            first_name=payload.firstName,
            last_name=payload.lastName,
            date_of_birth=payload.dateOfBirth,
            email=payload.email,
            display_name=display_name,
            skin_type="Not Specified",
            total_scans=0,
            average_score=Decimal("0.0"),
            status="ACTIVE",
        )
        database.upsert_user(new_profile)

        # Trigger Firebase email verification
        try:
            await _firebase_rest_call(
            "sendOobCode",
            {"requestType": "VERIFY_EMAIL", "email": payload.email},
        )
        except Exception:
        # Non-blocking: account is created even if email dispatch fails temporarily
            pass

        return {
            "success": True,
            "userId": user_record.uid,
            "message": "Account created successfully. Verification email sent!",
        }
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/login", summary="Login with Email/Password")
async def login_user(payload: LoginRequest):
    # Verify the email and password against Firebase and retrieve a fresh JWT
    try:
        # Verify the ID token from the frontend Firebase SDK
        decoded_token = firebase_auth.verify_id_token(payload.id_token)
        uid = decoded_token.get("uid")

        existing_user = database.get_user(uid)
        if not existing_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found. Please complete registration first.",
            )
        if existing_user.status == "PENDING_DELETION":
            database.reactivate_user_account(uid)

        # Mint backend JWT
        token = create_access_token(subject=uid, extra_claims={"role": "USER"})

        return {"success": True, "access_token": token, "token_type": "bearer", "user_id": uid}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid Firebase token: {str(e)}"
        ) from e


@router.post("/google", summary="Login or Signup with Google")
@router.post("/apple", summary="Login or Signup with Apple")
async def social_login(payload: SocialAuthRequest):
    try:
        # Verify the frontend's Apple/Google token using Firebase Admin
        decoded_token = firebase_auth.verify_id_token(payload.token)
        user_id = decoded_token["uid"]
        email = decoded_token.get("email", "unknown@email.com")
        display_name = decoded_token.get("name", "New User")

        # Sync with DynamoDB (for sign up, create a new profile)
        existing_user = database.get_user(user_id)
        if not existing_user:
            new_profile = UserProfile(
                user_id=user_id,
                email=email,
                display_name=display_name,
                skin_type="Not Specified",
                total_scans=0,
                average_score=0.0,
                status="ACTIVE",
            )
            database.upsert_user(new_profile)
        elif existing_user.status == "PENDING_DELETION":
            database.reactivate_user_account(user_id)

        token = create_access_token(subject=user_id, extra_claims={"role": "USER"})
        return {"success": True, "access_token": token, "token_type": "bearer", "userId": user_id}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token"
        ) from e


@router.post("/reset-password", summary="Request password reset")
async def reset_password(payload: ResetPasswordRequest):
    # Trigger the Firebase password reset email
    try:
        await _firebase_rest_call(
            "sendOobCode", {"requestType": "PASSWORD_RESET", "email": payload.email}
        )
    except HTTPException as e:
        # If the email isn't registered, swallow the 400 error silently
        if "EMAIL_NOT_FOUND" in str(e.detail):
            pass
        else:
            raise e

  # Always return the same message so attackers can't probe for valid emails
    return {
      "success": True,
      "message": "If an account exists, a password reset email has been sent.",
  }
