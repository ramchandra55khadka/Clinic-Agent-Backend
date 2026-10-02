"""Conversation history for the signed-in patient.

The chat turns are already persisted on every ``POST /chat``; these endpoints are
the read path that lets the client list a patient's threads, replay one after a
refresh or on a different device, and delete threads they no longer want.
Every query is scoped to ``user_id``, so another patient's ``session_id`` returns
404 rather than their transcript.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user_account import UserAccount
from app.schemas.common import MessageResponse
from app.schemas.conversations import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessageOut,
    ConversationOut,
)
from app.services import memory as memory_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _to_out(conversation) -> ConversationOut:
    return ConversationOut(
        session_id=conversation.session_id,
        title=conversation.title,
        message_count=conversation.message_count or 0,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get("/", response_model=ConversationListResponse)
def list_my_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Threads for the current patient, most recently active first."""
    conversations = memory_service.list_conversations(db, user_id=current_user.id, limit=limit, offset=offset)
    return ConversationListResponse(conversations=[_to_out(item) for item in conversations])


@router.get("/{session_id}", response_model=ConversationDetailResponse)
def get_my_conversation(
    session_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    before: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Replay one thread.

    Returns the newest ``limit`` turns (oldest first), which is what a chat view
    needs. Pass ``before=<message id>`` to walk backwards through older turns;
    ``has_more`` tells the client whether that button should still show.
    """
    conversation = memory_service.get_conversation(db, session_id=session_id, user_id=current_user.id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    page = memory_service.list_messages_before(
        db, session_id=session_id, user_id=current_user.id, before_id=before, limit=limit
    )
    has_more = bool(
        page
        and memory_service.has_messages_before(
            db, session_id=session_id, user_id=current_user.id, before_id=page[0].id
        )
    )
    return ConversationDetailResponse(
        session_id=conversation.session_id,
        title=conversation.title,
        summary=conversation.summary,
        message_count=conversation.message_count or 0,
        messages=[ConversationMessageOut.model_validate(message) for message in page],
        has_more=has_more,
    )


@router.delete("/{session_id}", response_model=MessageResponse)
def delete_my_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    if not memory_service.delete_conversation(db, session_id=session_id, user_id=current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return MessageResponse(message="Conversation deleted")
