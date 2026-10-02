"""Chat workflow request/response envelopes."""

from datetime import date as Date
from datetime import time as Time
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.appointment import AppointmentCreate


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1)
    doctor_id: int | None = None
    appointment_date: Date | None = None
    appointment_time: Time | None = None
    patient: AppointmentCreate | None = None



class ChatResponse(BaseModel):
    session_id: str
    intent: Literal["doctor_bio", "availability", "booking", "faq", "medical_web", "fallback"]
    response: str
    data: dict[str, Any] = {}
    chunks: list[dict[str, Any]] | None = None

