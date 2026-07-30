import uuid

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.schemas import SessionCreateResponse, TokenPayload
from app.services import database

router = APIRouter()


@router.post("", response_model=SessionCreateResponse, summary="Start a new analysis session")
async def create_session(current: TokenPayload = Depends(get_current_user)) -> SessionCreateResponse:
    # Generate a unique session ID
    session_id = uuid.uuid4().hex

    # Save session to DynamoDB
    database.save_session(user_id=current.sub, session_id=session_id)
    return SessionCreateResponse(session_id=session_id, status="OPEN")
