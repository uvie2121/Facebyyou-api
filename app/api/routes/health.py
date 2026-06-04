"""Health and readiness endpoints used by the load balancer / EC2 checks."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.core.config import settings
from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        version=__version__,
    )
