"""Request/response schemas and domain enums for the FaceByYou API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, EmailStr, Field


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class TokenPayload(BaseModel):
    sub: str
    email: str | None = None
    claims: dict[str, Any] = Field(default_factory=dict)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DevLoginRequest(BaseModel):
    """Local-only login used to issue dev JWTs without Cognito."""

    email: EmailStr
    user_id: str | None = None


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
class UserProfile(BaseModel):
    user_id: str
    email: EmailStr | None = None
    display_name: str | None = None
    skin_type: str | None = Field(
        default=None, description="e.g. oily | dry | combination | normal | sensitive"
    )
    created_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #
class PresignUploadRequest(BaseModel):
    filename: str
    content_type: str = Field(..., examples=["image/jpeg", "video/mp4"])


class PresignUploadResponse(BaseModel):
    upload_id: str
    object_key: str
    upload_url: str
    expires_in: int
    fields: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
class AnalysisStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class AnalysisRequest(BaseModel):
    object_key: str = Field(..., description="S3 key returned from the upload step")
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


class AnalysisResult(BaseModel):
    analysis_id: str
    user_id: str
    object_key: str
    status: AnalysisStatus
    skin_metrics: list[SkinMetric] = Field(default_factory=list)
    makeup_suggestions: list[MakeupSuggestion] = Field(default_factory=list)
    early_detection_flags: list[str] = Field(default_factory=list)
    skin_age_estimate: int | None = None
    disclaimer: str | None = None
    created_at: datetime | None = None


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
