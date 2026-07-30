from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.core.security import get_current_user
from app.models.schemas import AnalyticsEventRequest, TokenPayload
from app.services import database

# from mixpanel import Mixpanel
# mp = Mixpanel(settings.MIXPANEL_PROJECT_TOKEN)

router = APIRouter()


def process_event_background(user_id: str, event_name: str, metadata: dict):
    """The background worker that safely handles third-party API calls."""
    # Save to the secure AWS DynamoDB backup
    database.log_analytics_event(user_id, event_name, metadata)

    # Forward to Mixpanel
    # try:
    #     mp.track(user_id, event_name, metadata)
    # except Exception as e:
    #     logger.error(f"Mixpanel tracking failed: {str(e)}")


@router.post("/event", summary="Track a user behavioral event")
async def track_event(
    payload: AnalyticsEventRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
):
    """
    Ingests telemetry from the mobile app (e.g., 'scan_completed', 'profile_updated').
    Processing is handled in the background to ensure sub-50ms API response times.
    """

    if payload.metadata is None:
        payload.metadata = {}

    # Checking X-Forwarded-For is crucial when running behind an AWS Load Balancer or API Gateway,
    # otherwise request.client.host will just give the internal AWS IP.
    client_ip = request.headers.get("X-Forwarded-For", request.client.host)

    if client_ip and "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()

    payload.metadata["ip"] = client_ip

    # Hand the heavy lifting off to the background task
    background_tasks.add_task(
        process_event_background, current_user.sub, payload.eventName, payload.metadata
    )

    # Instantly tell the mobile app "Got it!"
    return {"success": True}
