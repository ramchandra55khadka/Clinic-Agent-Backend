"""Doctor info endpoints (RAG + the LangGraph chat workflow).

Both require an authenticated caller: chat can disclose clinic knowledge and
trigger bookings, so it must never be open to anonymous traffic.
"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from app.ai.chat_workflow.graph import run_clinic_chat, run_rag
from app.database.models import UserAccount
from app.database.schema import ChatRequest, ChatResponse, QueryRequest, QueryResponse
from app.dependencies.auth import get_current_user

router = APIRouter(tags=["doctor-info"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _user: UserAccount = Depends(get_current_user)):
    try:
        return run_clinic_chat(request)
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
