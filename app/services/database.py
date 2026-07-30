"""DynamoDB persistence for users and analysis records.

DynamoDB is the MVP datastore: serverless, cheap, and scales without ops work.
Access is wrapped behind small repository functions so we can later swap to RDS
without touching route handlers.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import AdminUser, AnalysisResult, UserProfile
from app.services.aws import dynamodb_resource, s3_client

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def upsert_user(profile: UserProfile) -> UserProfile:
    table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)
    # Dump to a literal JSON string to completely strip Python float typing
    json_string = profile.model_dump_json(exclude_none=True)

    # Parse it back into a dict, forcing all decimal numbers to become Decimals
    item: dict[str, Any] = json.loads(json_string, parse_float=Decimal)
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


def delete_user(user_id: str) -> None:
    table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)
    try:
        table.delete_item(Key={"user_id": user_id})
    except ClientError as exc:
        logger.error("delete_user failed", extra={"error": str(exc)})
        raise


# --------------------------------------------------------------------------- #
# Analyses
# --------------------------------------------------------------------------- #
def _to_dynamodb_dict(obj: Any) -> Any:
    """Recursively converts floats to Decimals for DynamoDB compatibility."""
    if isinstance(obj, float):
        # Convert float to string first to maintain precision, then to Decimal
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamodb_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamodb_dict(v) for v in obj]
    return obj


def save_analysis(result: AnalysisResult) -> AnalysisResult:
    table = dynamodb_resource().Table(settings.DYNAMODB_ANALYSES_TABLE)
    item = result.model_dump(mode="json", exclude_none=True)
    item.setdefault("created_at", _now_iso())
    item = _to_dynamodb_dict(item)
    try:
        table.put_item(Item=item)
    except ClientError as exc:
        logger.error("save_analysis failed", extra={"error": str(exc)})
        raise
    return AnalysisResult(**item)


def save_session(user_id: str, session_id: str, status: str = "OPEN") -> None:
    table = dynamodb_resource().Table(settings.DYNAMODB_SESSIONS_TABLE)

    # Calculate TTL: Current time + 24 hours
    ttl = int((datetime.now(UTC) + timedelta(hours=24)).timestamp())

    item = {
        "session_id": session_id,
        "user_id": user_id,
        "status": status,
        "created_at": _now_iso(),
        "ttl": ttl,
    }
    try:
        table.put_item(Item=item)
        logger.info(f"Session {session_id} initialized for user {user_id}")
    except ClientError as exc:
        logger.error("save_session failed", extra={"error": str(exc)})
        raise


def log_uploaded_image(user_id: str, session_id: str, image_url: str, image_type: str) -> None:
    table = dynamodb_resource().Table(settings.DYNAMODB_IMAGES_TABLE)
    table.put_item(
        Item={
            "image_id": f"img_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "session_id": session_id,
            "image_url": image_url,
            "image_type": image_type,
            "status": "active",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )


def update_session_status(user_id: str, session_id: str, new_status: str) -> None:
    """Update an owned session without allowing cross-user state changes."""
    table = dynamodb_resource().Table(settings.DYNAMODB_SESSIONS_TABLE)
    try:
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET #st = :val",
            ConditionExpression="user_id = :user_id AND #st = :open_status",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":val": new_status,
                ":user_id": user_id,
                ":open_status": "OPEN",
            },
        )
        logger.info(
            "Session status updated", extra={"session_id": session_id, "status": new_status}
        )
    except ClientError as exc:
        logger.error("update_session_status failed", extra={"error": str(exc)})
        raise


def get_session(session_id: str) -> dict | None:
    """
    Fetches a session metadata record from DynamoDB.
    Returns the dictionary of the session if found, or None if it doesn't exist.
    """

    table = dynamodb_resource().Table(settings.DYNAMODB_SESSIONS_TABLE)

    try:
        resp = table.get_item(Key={"session_id": session_id})
        return resp.get("Item")

    except ClientError as exc:
        logger.error("get_session failed", extra={"error": str(exc)})
        raise


def get_analysis(user_id: str, analysis_id: str) -> AnalysisResult | None:
    table = dynamodb_resource().Table(settings.DYNAMODB_ANALYSES_TABLE)
    try:
        resp = table.get_item(Key={"user_id": user_id, "analysis_id": analysis_id})
    except ClientError as exc:
        logger.error("get_analysis failed", extra={"error": str(exc)})
        raise
    item = resp.get("Item")
    return AnalysisResult(**item) if item else None


def get_analyses_by_session(user_id: str, session_id: str) -> list[AnalysisResult]:
    table = dynamodb_resource().Table(settings.DYNAMODB_ANALYSES_TABLE)
    try:
        resp = table.query(
            KeyConditionExpression="user_id = :uid",
            FilterExpression="session_id = :sid",
            ExpressionAttributeValues={":uid": user_id, ":sid": session_id},
        )
        return [AnalysisResult(**item) for item in resp.get("Items", [])]
    except ClientError as exc:
        logger.error("list_analysis_by_session failed", extra={"error": str(exc)})
        raise


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


def update_user_score_stats(user_id: str, new_score: float) -> None:
    """Updates the running average and total scans for a user profile."""
    table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)

    try:
        # Fetch current stats
        user = get_user(user_id)
        if not user:
            logger.warning(f"Could not update stats: User {user_id} not found.")
            return

        # Extract current values (defaulting to 0 if this is the user's first scan)
        current_total = getattr(user, "total_scans", 0)
        current_avg = float(getattr(user, "average_score", 0.0))
        current_best = float(getattr(user, "best_score", 0.0))

        previous_score = float(getattr(user, "latest_score", 0.0))

        # Calculate new running average
        new_total = current_total + 1
        new_avg = ((current_avg * current_total) + new_score) / new_total
        new_best = max(current_best, new_score)
        delta = new_score - previous_score if current_total > 0 else 0.0

        # Update the record in DynamoDB
        # Note: We cast to Decimal because of DynamoDB float limitations
        table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET total_scans = :t, average_score = :a, best_score = :b, latest_score = :l, previous_score = :p, updated_at = :u",
            ExpressionAttributeValues={
                ":t": new_total,
                ":a": Decimal(str(round(new_avg, 2))),
                ":b": Decimal(str(round(new_best, 2))),
                ":l": Decimal(str(round(new_score, 2))),
                ":p": Decimal(str(round(previous_score, 2))),
                ":u": _now_iso(),
            },
        )
        logger.info(
            f"Stats updated for {user_id} | Total: {new_total} | "
            f"Avg: {new_avg:.2f} | Best: {new_best:.2f} | Delta: {delta:+.2f}"
        )

    except ClientError as exc:
        logger.error("update_user_score_stats failed", extra={"error": str(exc)})
        raise


def get_last_user_feedback(user_id: str) -> dict[str, list[str]] | None:
    """
    Queries DynamoDB for the user's most recent analysis and extracts
    both previous improvements and recommendations for stateful feedback tracking.
    """
    try:
        dynamodb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
        table = dynamodb.Table(settings.DYNAMODB_ANALYSES_TABLE)

        # Analysis IDs are random, so choose the newest record by its timestamp.
        response = table.query(
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=False,
        )

        items = response.get("Items", [])
        if not items:
            return None

        last_analysis = max(items, key=lambda item: item.get("created_at", ""))
        ai_feedback = last_analysis.get("ai_feedback", {})
        improvements = ai_feedback.get("improvements", [])
        recommendations = ai_feedback.get("recommendations", [])

        if not improvements and not recommendations:
            return None

        return {
            "improvements": improvements,
            "recommendations": recommendations,
        }

    except Exception as e:
        logger.warning(f"Could not retrieve last feedback for user {user_id}: {e}")
        return None


def get_last_user_recommendation(user_id: str) -> str | None:
    """Legacy helper returning only the primary recommendation string."""
    feedback = get_last_user_feedback(user_id)
    if feedback and feedback.get("recommendations"):
        return feedback["recommendations"][0]
    return None



# --------------------------------------------------------------------------- #
# Admin & RBAC
# --------------------------------------------------------------------------- #
def get_all_admins() -> list[AdminUser]:
    """Fetches all admin and analyst accounts from the DynamoDB table."""
    table = dynamodb_resource().Table(settings.DYNAMODB_ADMIN_TABLE)
    try:
        # Scan reads the entire table.
        # For small team lists (MVP), this is perfectly efficient.
        response = table.scan()
        items = response.get("Items", [])

        return [AdminUser(**item) for item in items]

    except Exception as exc:
        logger.error("get_all_admins scan failed", extra={"error": str(exc)})
        raise


def get_admin_user(user_id: str) -> AdminUser | None:
    table = dynamodb_resource().Table(settings.DYNAMODB_ADMIN_TABLE)
    try:
        resp = table.get_item(Key={"user_id": user_id})
    except ClientError as exc:
        logger.error("get_admin_user failed", extra={"error": str(exc)})
        raise
    item = resp.get("Item")
    return AdminUser(**item) if item else None


def get_admin_by_email(email: str) -> AdminUser | None:
    """Fetches an admin record by filtering the table for a specific email."""
    table = dynamodb_resource().Table(settings.DYNAMODB_ADMIN_TABLE)
    try:
        response = table.scan(FilterExpression=Attr("email").eq(email))
        items = response.get("Items", [])
        if not items:
            return None

        return AdminUser(**items[0])
    except ClientError as exc:
        logger.error("get_admin_by_email failed", extra={"error": str(exc)})
        raise


def create_admin_user(admin_data: AdminUser) -> None:
    table = dynamodb_resource().Table(settings.DYNAMODB_ADMIN_TABLE)
    item = admin_data.model_dump(mode="json", exclude_none=True)
    try:
        table.put_item(Item=item)
        logger.info(f"Admin user {admin_data.user_id} created with role {admin_data.role}.")
    except ClientError as exc:
        logger.error("create_admin_user failed", extra={"error": str(exc)})
        raise


def delete_admin_user(admin_id: str) -> None:
    table = dynamodb_resource().Table(settings.DYNAMODB_ADMIN_TABLE)
    try:
        table.delete_item(Key={"user_id": admin_id})
        logger.info(f"Admin privileges revoked for {admin_id}.")
    except ClientError as exc:
        logger.error("delete_admin_user failed", extra={"error": str(exc)})
        raise


# --------------------------------------------------------------------------- #
# Audit Logging
# --------------------------------------------------------------------------- #
def log_admin_action(admin_id: str, action: str, entity_type: str, entity_id: str) -> None:
    table = dynamodb_resource().Table(settings.DYNAMODB_AUDIT_TABLE)
    item = {
        "audit_id": f"audit_{datetime.now(UTC).timestamp()}",
        "admin_id": admin_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "timestamp": _now_iso(),
    }
    try:
        table.put_item(Item=item)
    except ClientError as exc:
        logger.error("log_admin_action failed", extra={"error": str(exc)})
        raise


# --------------------------------------------------------------------------- #
# Platform Metrics & Moderation
# --------------------------------------------------------------------------- #
def get_platform_aggregates() -> dict[str, Any]:
    """Calculates platform statistics.
    - total_users: Total number of users
    - daily_active_users: Number of unique users who have performed an analysis in the last 24 hours
    - total_scans: Total number of scans performed
    - average_score: Average score of all analyses
    """
    try:
        users_table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)
        users_count = users_table.scan(Select="COUNT").get("Count", 0)

        analyses_table = dynamodb_resource().Table(settings.DYNAMODB_ANALYSES_TABLE)
        response = analyses_table.scan()
        items = response.get("Items", [])
        total_scans = len(items)

        scores = [
            float(item.get("category_scores", {}).get("overall_score", 0))
            for item in items
            if item.get("category_scores")
            and item.get("category_scores").get("overall_score") is not None
        ]
        average_score = sum(scores) / len(scores) if scores else 0.0

        cutoff_time = datetime.now(UTC) - timedelta(hours=24)
        analytics_table = dynamodb_resource().Table(settings.DYNAMODB_ANALYTICS_TABLE)
        analytics_response = analytics_table.scan()
        analytics_items = analytics_response.get("Items", [])

        print(f"DEBUG: Found {len(analytics_items)} total items in analytics table.")

        # Filter unique users active within the last 24 hours
        active_users_24h = set()
        for item in analytics_items:
            uid = item.get("user_id")
            ts_str = item.get("timestamp")
            print(f"DEBUG: Processing user {uid} with timestamp {ts_str}")
            if uid and ts_str:
                try:
                    # Parse the stored ISO timestamp back to a datetime object
                    event_time = datetime.fromisoformat(ts_str)
                    print(
                        f"DEBUG: Parsed time {event_time} vs cutoff {cutoff_time}. Is newer? {event_time >= cutoff_time}"
                    )
                    if event_time >= cutoff_time:
                        active_users_24h.add(uid)
                except Exception as e:
                    print(f"DEBUG ERROR parsing date: {e}")
                    continue

        dau_count = len(active_users_24h)

    except ClientError as exc:
        logger.error("get_platform_aggregates failed", extra={"error": str(exc)})
        raise

    return {
        "total_users": int(users_count),
        "daily_active_users": int(dau_count),
        "total_scans": int(total_scans),
        "average_score": round(float(average_score), 1),
    }


def get_all_users() -> list[UserProfile]:
    """
    WARNING: Full table scan. Appropriate only for MVP scale.
    """
    table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)
    try:
        resp = table.scan(ProjectionExpression="user_id, email, total_scans, average_score")
    except ClientError as exc:
        logger.error("get_all_users failed", extra={"error": str(exc)})
        raise

    return [UserProfile(**item) for item in resp.get("Items", [])]


def update_user_status(user_id: str, status: str, deletion_scheduled_at: str) -> None:
    table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)
    table.update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET #st = :status_val, #ds = :date_val",
        ExpressionAttributeNames={"#st": "status", "#ds": "deletion_scheduled_at"},
        ExpressionAttributeValues={":status_val": status, ":date_val": deletion_scheduled_at},
    )


def purge_user_data(user_id: str) -> None:
    """Permanently remove a user's S3 media and DynamoDB records after retention expires."""
    s3 = s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.S3_UPLOAD_BUCKET, Prefix=f"uploads/{user_id}/"):
        objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        if objects:
            s3.delete_objects(Bucket=settings.S3_UPLOAD_BUCKET, Delete={"Objects": objects})

    db = dynamodb_resource()

    def delete_query_results(table_name: str, key_fields: list[str]) -> None:
        table = db.Table(table_name)
        start_key = None
        while True:
            query_args = {"KeyConditionExpression": Key("user_id").eq(user_id)}
            if start_key:
                query_args["ExclusiveStartKey"] = start_key
            response = table.query(**query_args)
            with table.batch_writer() as batch:
                for item in response.get("Items", []):
                    batch.delete_item(Key={field: item[field] for field in key_fields})
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break

    def delete_scan_results(table_name: str, key_field: str, filter_expression) -> None:
        table = db.Table(table_name)
        start_key = None
        while True:
            scan_args = {"FilterExpression": filter_expression}
            if start_key:
                scan_args["ExclusiveStartKey"] = start_key
            response = table.scan(**scan_args)
            with table.batch_writer() as batch:
                for item in response.get("Items", []):
                    batch.delete_item(Key={key_field: item[key_field]})
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break

    delete_query_results(settings.DYNAMODB_ANALYSES_TABLE, ["user_id", "analysis_id"])
    delete_scan_results(settings.DYNAMODB_SESSIONS_TABLE, "session_id", Attr("user_id").eq(user_id))
    delete_scan_results(settings.DYNAMODB_IMAGES_TABLE, "image_id", Attr("user_id").eq(user_id))
    delete_scan_results(settings.DYNAMODB_ANALYTICS_TABLE, "event_id", Attr("user_id").eq(user_id))
    delete_scan_results(settings.DYNAMODB_AUDIT_TABLE, "audit_id", Attr("entity_id").eq(user_id))

    users = db.Table(settings.DYNAMODB_USERS_TABLE)
    users.delete_item(Key={"user_id": user_id})


def reactivate_user_account(user_id: str) -> None:
    """Cancel a user-requested deletion after a successful login during the 30-day period."""
    table = dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)
    table.update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET #st = :active REMOVE deletion_scheduled_at",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":active": "ACTIVE"},
    )


def get_user_images(limit: int = 50) -> list[dict]:
    """Fetches a list of recently uploaded images for admin moderation."""
    table = dynamodb_resource().Table(settings.DYNAMODB_IMAGES_TABLE)
    try:
        # A simple scan for MVP. For larger scale, a secondary index
        # sorted by upload date or a "flagged" status would be used.
        response = table.scan(Limit=limit)
        return response.get("Items", [])
    except ClientError as exc:
        logger.error("get_user_images failed", extra={"error": str(exc)})
        raise


def get_image_metadata(image_id: str) -> dict | None:
    table = dynamodb_resource().Table(settings.DYNAMODB_IMAGES_TABLE)
    try:
        resp = table.get_item(Key={"image_id": image_id})
    except ClientError as exc:
        logger.error("get_image_metadata failed", extra={"error": str(exc)})
        raise
    return resp.get("Item")


def delete_image_record(image_id: str) -> None:
    table = dynamodb_resource().Table(settings.DYNAMODB_IMAGES_TABLE)
    try:
        table.delete_item(Key={"image_id": image_id})
    except ClientError as exc:
        logger.error("delete_image_record failed", extra={"error": str(exc)})
        raise


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #
def log_analytics_event(user_id: str, event_name: str, metadata: dict) -> None:
    """Stores a raw analytics event in DynamoDB for permanent backup."""
    table = dynamodb_resource().Table(settings.DYNAMODB_ANALYTICS_TABLE)

    item = {
        "event_id": f"evt_{datetime.now(UTC).timestamp()}_{user_id[-6:]}",
        "user_id": user_id,
        "event_name": event_name,
        "metadata": metadata,
        "timestamp": _now_iso(),
    }

    try:
        table.put_item(Item=item)
    except ClientError as exc:
        logger.error("log_analytics_event failed", extra={"error": str(exc)})
        # No error raised here; analytics failing shouldn't break the user's app experience.


# --------------------------------------------------------------------------- #
# Local Development Initialization
# --------------------------------------------------------------------------- #


def initialize_database():
    """Ensure required tables exist in the local DynamoDB container."""
    # Safety Check: Only run this if we are pointed at local Docker
    if not os.getenv("DYNAMODB_ENDPOINT_URL"):
        logger.info("Skipping table creation: Not running against local DynamoDB.")
        return

    db = dynamodb_resource()

    # Helper function to reduce repetition
    def _create_table(name, key_schema, attr_defs):
        try:
            db.Table(name).load()
            logger.info(f"Table '{name}' already exists.")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info(f"Creating table '{name}'...")
                table = db.create_table(
                    TableName=name,
                    KeySchema=key_schema,
                    AttributeDefinitions=attr_defs,
                    BillingMode="PAY_PER_REQUEST",
                )
                table.meta.client.get_waiter("table_exists").wait(TableName=name)
                logger.info(f"Table '{name}' created.")

    # 1. Users
    _create_table(
        settings.DYNAMODB_USERS_TABLE,
        [{"AttributeName": "user_id", "KeyType": "HASH"}],
        [{"AttributeName": "user_id", "AttributeType": "S"}],
    )

    # 2. Analyses
    _create_table(
        settings.DYNAMODB_ANALYSES_TABLE,
        [
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "analysis_id", "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "analysis_id", "AttributeType": "S"},
        ],
    )

    # 3. Admin Users
    _create_table(
        settings.DYNAMODB_ADMIN_TABLE,
        [{"AttributeName": "user_id", "KeyType": "HASH"}],
        [{"AttributeName": "user_id", "AttributeType": "S"}],
    )

    # 4. Audit Logs
    _create_table(
        settings.DYNAMODB_AUDIT_TABLE,
        [{"AttributeName": "audit_id", "KeyType": "HASH"}],
        [{"AttributeName": "audit_id", "AttributeType": "S"}],
    )

    # 6. Images
    _create_table(
        settings.DYNAMODB_IMAGES_TABLE,
        [{"AttributeName": "image_id", "KeyType": "HASH"}],
        [{"AttributeName": "image_id", "AttributeType": "S"}],
    )

    # 7. Analytics
    _create_table(
        settings.DYNAMODB_ANALYTICS_TABLE,
        [{"AttributeName": "event_id", "KeyType": "HASH"}],
        [{"AttributeName": "event_id", "AttributeType": "S"}],
    )

    # 8. Sessions
    _create_table(
        settings.DYNAMODB_SESSIONS_TABLE,
        [{"AttributeName": "session_id", "KeyType": "HASH"}],
        [{"AttributeName": "session_id", "AttributeType": "S"}],
    )
