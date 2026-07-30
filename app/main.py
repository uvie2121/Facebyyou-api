"""FastAPI application entrypoint for the FaceByYou API."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import firebase_admin
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from firebase_admin import credentials

from app import __version__
from app.api.routes import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.services.cleanup import process_pending_deletions
from app.services.database import initialize_database

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Starting FaceByYou API",
        extra={"environment": settings.ENVIRONMENT, "version": __version__},
    )

    # Spin up local tables if they don't exist
    try:
        initialize_database()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    # Run retention cleanup outside request handling.  The scheduler must be
    # started before yielding control to FastAPI and stopped during shutdown.
    scheduler = BackgroundScheduler()
    scheduler.add_job(process_pending_deletions, "interval", days=1)
    scheduler.start()
    logger.info("Background deletion scheduler started")

    try:
        yield
    finally:
        logger.info("Shutting down FaceByYou API")
        scheduler.shutdown(wait=False)
        logger.info("Background deletion scheduler stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    description="AI-powered skin analysis and virtual makeup backend.",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- FIREBASE INITIALIZATION ---
# Check if it's already initialized to prevent errors when the server reloads
if not firebase_admin._apps:
    credential_path = settings.FIREBASE_ADMIN_CREDENTIALS_PATH

    if not credential_path:
        raise RuntimeError("FIREBASE_ADMIN_CREDENTIALS_PATH must be configured.")

    path = Path(credential_path)
    if not path.is_file():
        raise RuntimeError(f"Firebase Admin credential file was not found: {path}")

    firebase_admin.initialize_app(credentials.Certificate(str(path)))


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id and emit a structured access log per request."""
    request_id = request.headers.get("x-request-id", uuid.uuid4().hex)
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error", extra={"path": request.url.path})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", include_in_schema=False)
async def root():
    return {"service": settings.PROJECT_NAME, "version": __version__, "docs": "/docs"}


# onboarding: testing ci pipeline
