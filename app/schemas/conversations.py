"""Conversation threads and message transcripts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationOut(BaseModel):
    session_id: str
    title: str | None
    message_count: int
    created_at: Any
    updated_at: Any



class ConversationListResponse(BaseModel):
    conversations: list[ConversationOut]



class ConversationUpdate(BaseModel):
    """Rename request for a thread (``PATCH /conversations/{session_id}``)."""

    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def _title_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned



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

