"""Conversation threads and message transcripts."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ConversationOut(BaseModel):
    session_id: str
    title: str | None
    message_count: int
    created_at: Any
    updated_at: Any



class ConversationListResponse(BaseModel):
    conversations: list[ConversationOut]



class ConversationMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    intent: str | None
    created_at: Any



class ConversationDetailResponse(BaseModel):
    session_id: str
    title: str | None
    summary: str | None
    message_count: int
    messages: list[ConversationMessageOut]
    has_more: bool = False

