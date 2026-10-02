"""Doctor info endpoints (RAG + the LangGraph chat workflow).

Both require an authenticated caller: chat can disclose clinic knowledge and
trigger bookings, so it must never be open to anonymous traffic.
"""

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.ai.chat_workflow.graph import run_clinic_chat, run_rag
from app.ai.chat_workflow.memory import get_session, save_session
from app.api.deps import get_current_user
from app.db.session import SessionLocal, get_db
from app.models.user_account import UserAccount
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.query import QueryRequest, QueryResponse
from app.services import memory as memory_service

router = APIRouter(tags=["doctor-info"])


def _extract_memories_background(user_id: str, session_id: str, message: str) -> None:
    with SessionLocal() as db:
        user = db.get(UserAccount, user_id)
        if user is None or not memory_service.memory_enabled(db, user):
            return
        conversation = memory_service.get_conversation(db, session_id=session_id, user_id=user_id)
        if conversation is None:
            return
        user_turns = sum(1 for row in memory_service.list_messages(db, session_id=session_id, user_id=user_id) if row.role == "user")
        if user_turns % 4 != 0:
            return
        memory_service.extract_memories_from_message(
            db,
            user=user,
            message=message,
            source_conversation_id=conversation.id,
        )


def _refresh_summary_background(session_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        memory_service.refresh_summary(db, session_id=session_id, user_id=user_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        memories = (
            memory_service.retrieve_memories(db, user_id=current_user.id, query=request.message)
            if memory_service.memory_enabled(db, current_user)
            else []
        )
        session_id = request.session_id or str(uuid4())
        conversation_state = get_session(db, session_id, current_user.id)

        # Replay the transcript so this turn can refer to everything said before.
        # Only the recent window is loaded verbatim; anything older lives in the
        # rolling summary, which keeps long threads inside the context window.
        history = memory_service.recent_messages(
            db, session_id=session_id, user_id=current_user.id
        )
        summary = memory_service.get_summary(db, session_id=session_id, user_id=current_user.id)

        result, new_state = run_clinic_chat(
            request,
            session_id=session_id,
            conversation_state=conversation_state,
            long_term_memories=memory_service.render_memories_for_prompt(memories),
            history=history,
            summary=summary,
        )

        save_session(db, session_id, current_user.id, new_state)

        memory_service.save_message(
            db,
            session_id=result.session_id,
            user_id=current_user.id,
            role="user",
            content=request.message,
            intent=result.intent,
        )
        memory_service.save_message(
            db,
            session_id=result.session_id,
            user_id=current_user.id,
            role="assistant",
            content=result.response,
            intent=result.intent,
        )
        background_tasks.add_task(_extract_memories_background, current_user.id, result.session_id, request.message)
        background_tasks.add_task(_refresh_summary_background, result.session_id, current_user.id)
        return result
    except Exception as exc:
        # Log the detail, return a generic message: internals stay server-side.
        logger.exception("Chat workflow failed: {}", type(exc).__name__)
        raise HTTPException(status_code=500, detail="The assistant could not process that request.") from exc


@router.post("/rag", response_model=QueryResponse)
async def rag(request: QueryRequest, _user: UserAccount = Depends(get_current_user)):
    try:
        return run_rag(request)
    except Exception as exc:
        logger.exception("RAG query failed: {}", type(exc).__name__)
        raise HTTPException(status_code=500, detail="The knowledge base could not answer that query.") from exc
