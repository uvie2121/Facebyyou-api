"""Application configuration.

All runtime configuration is loaded from environment variables (12-factor).
In production these values are injected from AWS Secrets Manager / SSM by the
EC2 bootstrap script, never committed to source control.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    PROJECT_NAME: str = "FaceByYou API"
    ENVIRONMENT: str = Field(default="dev", description="dev | staging | production")
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # --- Security / Auth ---
    # For the MVP we verify JWTs minted by Firebase(or AWS Cognito). The secret
    # is only used for locally-issued dev tokens; in prod we validate against the
    # provider's JWKS endpoint.
    JWT_SECRET: str = "change-me-in-secrets-manager"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    COGNITO_REGION: str | None = None
    COGNITO_USER_POOL_ID: str | None = None
    COGNITO_APP_CLIENT_ID: str | None = None
    FIREBASE_WEB_API_KEY: str | None = None
    FIREBASE_ADMIN_CREDENTIALS_PATH: str | None = None

    # --- CORS ---
    BACKEND_CORS_ORIGINS: list[str] = ["*"]

    # --- AWS ---
    AWS_REGION: str = "us-east-1"
    # boto3 resolves credentials from the EC2 instance profile (IAM role) in
    # production, so we never set AWS keys here.

    # --- S3 (face image / video uploads) ---
    S3_UPLOAD_BUCKET: str = "facebyyou-uploads-dev"
    S3_PRESIGNED_URL_TTL_SECONDS: int = 900
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_UPLOAD_CONTENT_TYPES: list[str] = [
        "image/jpeg",
        "image/png",
        "image/heic",
        "video/mp4",
        "video/quicktime",
    ]

    # --- DynamoDB ---
    DYNAMODB_USERS_TABLE: str = "facebyyou-users-dev"
    DYNAMODB_ANALYSES_TABLE: str = "facebyyou-analyses-dev"
    DYNAMODB_SESSIONS_TABLE: str = "facebyyou-sessions-dev"
    DYNAMODB_ADMIN_TABLE: str = "facebyyou-admin-users-dev"
    DYNAMODB_AUDIT_TABLE: str = "facebyyou-audit-logs-dev"
    DYNAMODB_IMAGES_TABLE: str = "facebyyou-images-dev"
    DYNAMODB_ANALYTICS_TABLE: str = "facebyyou-analytics-dev"
    DYNAMODB_ENDPOINT_URL: str | None = None  # set to http://localhost:8001 for local DynamoDB

    # --- AI Services ---
    OLLAMA_API_URL: str = "http://localhost:11434/api/generate"

    NIM_API_KEY: str | None = None
    NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NIM_MODEL_NAME: str = "nvidia/nemotron-nano-12b-v2-vl"
    NIM_TIMEOUT_SECONDS: int = 45
    NIM_IMAGE_URL_TTL_SECONDS: int = 120

    # --- Mixpanel ---
    MIXPANEL_PROJECT_TOKEN: str | None = None

    @field_validator("BACKEND_CORS_ORIGINS", "ALLOWED_UPLOAD_CONTENT_TYPES", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Allow comma-separated env strings for list fields."""
        if isinstance(v, str) and not v.startswith("["):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()


settings = get_settings()
