from datetime import UTC, datetime

from firebase_admin import auth as firebase_auth

from app.core.config import settings
from app.services import database


def process_pending_deletions():
    """Scans for users whose 30-day grace period has elapsed and hard-deletes them."""
    print("Running scheduled task: Checking for expired user accounts...")

    table = database.dynamodb_resource().Table(settings.DYNAMODB_USERS_TABLE)

    # Scan or query items where status is PENDING_DELETION
    # (For production tables with lots of records, a GSI on status is optimal, but a FilterExpression works for development)
    now = datetime.now(UTC)
    start_key = None

    while True:
        scan_args = {
            "FilterExpression": "#st = :val",
            "ExpressionAttributeNames": {"#st": "status"},
            "ExpressionAttributeValues": {":val": "PENDING_DELETION"},
        }
        if start_key:
            scan_args["ExclusiveStartKey"] = start_key
        response = table.scan(**scan_args)

        for user in response.get("Items", []):
            user_id = user.get("user_id")
            scheduled_str = user.get("deletion_scheduled_at")

            if not user_id or not scheduled_str:
                continue

            scheduled_date = datetime.fromisoformat(scheduled_str)

            if now >= scheduled_date:
                print(f"30-day window elapsed for user {user_id}. Executing permanent deletion...")
                try:
                    firebase_auth.delete_user(user_id)
                except Exception as e:
                    print(f"Firebase user {user_id} already deleted or error: {e}")

                database.purge_user_data(user_id)
                print(f"Successfully purged user {user_id}")

        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            break
