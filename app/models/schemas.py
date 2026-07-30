"""Request/response schemas and domain enums for the FaceByYou API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field
from pydantic.alias_generators import to_camel


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class TokenPayload(BaseModel):
    sub: str
    email: str | None = None
    role: AdminRole | None = None
    claims: dict[str, Any] = Field(default_factory=dict)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DevLoginRequest(BaseModel):
    """Local-only login used to issue dev JWTs without Firebase."""

    email: EmailStr
    user_id: str | None = None


class RegisterRequest(BaseModel):
    firstName: str
    lastName: str
    dateOfBirth: date
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    id_token: str


class SocialAuthRequest(BaseModel):
    token: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
class UserProfile(BaseModel):
    user_id: str
    email: EmailStr | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    status: Literal["ACTIVE", "PENDING_DELETION"] = "ACTIVE"
    display_name: str | None = None
    skin_type: str | None = Field(
        default=None, description="e.g. oily | dry | combination | normal | sensitive"
    )
    created_at: datetime | None = None
    total_scans: int = 0
    latest_score: Decimal = Decimal("0.00")
    previous_score: Decimal = Decimal("0.00")
    best_score: Decimal = Decimal("0.00")
    average_score: Decimal = Decimal("0.00")
    deletion_scheduled_at: str | None = None

    @computed_field
    @property
    def delta(self) -> float:
        """Calculates the improvement delta dynamically."""
        if self.total_scans > 0:
            return round(self.latest_score - self.previous_score, 2)
        return 0.0


class UserProfileUpdate(BaseModel):
    display_name: str | None = None
    skin_type: str | None = None


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
class SessionResponse(BaseModel):
    session_id: str
    status: Literal["OPEN", "LOCKED"] = "OPEN"
    urls: dict[str, PresignedUpload] | None = None


class SessionCreateResponse(BaseModel):
    """Response for creating a session before any upload forms are requested."""
    session_id: str
    status: Literal["OPEN", "LOCKED"] = "OPEN"


class PresignedUpload(BaseModel):
    """S3 browser/mobile POST target and the fields that must accompany the file."""
    url: str
    fields: dict[str, str]


class SessionUploadUrlResponse(BaseModel):
    session_id: str
    view: Literal["front", "left", "right"]
    upload_url: str
    upload_fields: dict[str, str]
    expires_in: int


# --------------------------------------------------------------------------- #
# Session Upload
# --------------------------------------------------------------------------- #
class SessionCreateRequest(BaseModel):
    content_type: str = Field(..., examples=["image/jpeg"])
    files: dict[str, str] = Field(
        ..., examples=[{"front": "selfie.jpg", "left": "side.jpg", "right": "side_profile.jpg"}]
    )


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
class ValidationRequest(BaseModel):
    view: Literal["front", "left", "right"]


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
class AnalysisStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class AnalysisRequest(BaseModel):
    analysis_types: list[str] = Field(
        default_factory=lambda: ["skin", "makeup"],
        description="Subset of: skin, makeup, early_detection",
    )


class SkinMetric(BaseModel):
    name: str
    score: float = Field(..., ge=0, le=100)
    note: str | None = None


class MakeupSuggestion(BaseModel):
    product_type: str
    shade: str
    hex_color: str | None = None
    reason: str | None = None


class LightingCondition(str, Enum):
    HARSH_FLASH = "harsh_flash"
    TOO_DARK = "too_dark"
    BALANCED = "balanced"


class CategoryScores(BaseModel):
    foundation_score: float = Field(..., ge=0, le=100)
    blend_score: float = Field(..., ge=0, le=100)
    contour_score: float = Field(..., ge=0, le=100)
    eyes_score: float = Field(..., ge=0, le=100)
    lips_score: float = Field(..., ge=0, le=100)
    symmetry_score: float = Field(..., ge=0, le=100)
    base_finish_score: float = Field(..., ge=0, le=100)
    color_balance_score: float = Field(..., ge=0, le=100)
    overall_score: float = Field(..., ge=0, le=100)


class AIFeedback(BaseModel):
    glam_type: str
    strengths: list[str]
    improvements: list[str]
    recommendations: list[str]


class AnalysisResult(BaseModel):
    analysis_id: str
    user_id: str
    session_id: str
    status: AnalysisStatus
    skin_metrics: list[SkinMetric] = Field(default_factory=list)
    category_scores: CategoryScores
    ai_feedback: AIFeedback
    confidence_score: float
    makeup_suggestions: list[MakeupSuggestion] = Field(default_factory=list)
    early_detection_flags: list[str] = Field(default_factory=list)
    skin_age_estimate: int | None = None
    disclaimer: str | None = None
    created_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Admin
# --------------------------------------------------------------------------- #
class AdminRole(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    USER = "USER"  # Regular user, not an admin


class AdminUser(BaseModel):
    user_id: str
    email: EmailStr
    role: AdminRole
    created_at: datetime


class AdminLoginRequest(BaseModel):
    id_token: str = Field(..., description="Firebase ID token for admin login")


class AdminInviteRequest(BaseModel):
    email: EmailStr
    role: AdminRole


class AdminMetrics(BaseModel):
    total_users: int
    daily_active_users: int
    total_scans: int
    average_score: float

    # magic config
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #
class AnalyticsEventRequest(BaseModel):
    eventName: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    environment: str
    version: str


class MessageResponse(BaseModel):
    message: str
