"""Versioned API routers."""

from fastapi import APIRouter

from app.api.routes import (
    admin,
    analysis,
    analytics,
    auth,
    health,
    history,
    sessions,
    uploads,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(uploads.router, prefix="/sessions", tags=["uploads"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(history.router, prefix="/history", tags=["Analytics & History"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin Dashboard"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics & Telemetry"])
