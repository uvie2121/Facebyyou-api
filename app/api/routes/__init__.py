"""Versioned API routers."""

from fastapi import APIRouter

from app.api.routes import analysis, auth, health, uploads, users

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
