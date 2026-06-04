"""DynamoDB persistence for users and analysis records.

DynamoDB is the MVP datastore: serverless, cheap, and scales without ops work.
Access is wrapped behind small repository functions so we can later swap to RDS
without touching route handlers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import AnalysisResult, UserProfile
from app.services.aws import dynamodb_resource

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def upsert_user(profile: UserProfile) -> UserProfile:
    table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)
    item: dict[str, Any] = profile.model_dump(mode="json", exclude_none=True)
    item.setdefault("created_at", _now_iso())
    try:
        table.put_item(Item=item)
    except ClientError as exc:
        logger.error("upsert_user failed", extra={"error": str(exc)})
        raise
    return UserProfile(**item)


def get_user(user_id: str) -> UserProfile | None:
    table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)
    try:
        resp = table.get_item(Key={"user_id": user_id})
    except ClientError as exc:
        logger.error("get_user failed", extra={"error": str(exc)})
        raise
    item = resp.get("Item")
    return UserProfile(**item) if item else None


# --------------------------------------------------------------------------- #
# Analyses
# --------------------------------------------------------------------------- #
def save_analysis(result: AnalysisResult) -> AnalysisResult:
    table = dynamodb_resource().Table(settings.DYNAMODB_ANALYSES_TABLE)
    item = result.model_dump(mode="json", exclude_none=True)
    item.setdefault("created_at", _now_iso())
    try:
        table.put_item(Item=item)
    except ClientError as exc:
        logger.error("save_analysis failed", extra={"error": str(exc)})
        raise
    return AnalysisResult(**item)


def get_analysis(user_id: str, analysis_id: str) -> AnalysisResult | None:
    table = dynamodb_resource().Table(settings.DYNAMODB_ANALYSES_TABLE)
    try:
        resp = table.get_item(Key={"user_id": user_id, "analysis_id": analysis_id})
    except ClientError as exc:
        logger.error("get_analysis failed", extra={"error": str(exc)})
        raise
    item = resp.get("Item")
    return AnalysisResult(**item) if item else None


def list_analyses(user_id: str, limit: int = 25) -> list[AnalysisResult]:
    table = dynamodb_resource().Table(settings.DYNAMODB_ANALYSES_TABLE)
    try:
        resp = table.query(
            KeyConditionExpression="user_id = :uid",
            ExpressionAttributeValues={":uid": user_id},
            Limit=limit,
            ScanIndexForward=False,
        )
    except ClientError as exc:
        logger.error("list_analyses failed", extra={"error": str(exc)})
        raise
    return [AnalysisResult(**item) for item in resp.get("Items", [])]
