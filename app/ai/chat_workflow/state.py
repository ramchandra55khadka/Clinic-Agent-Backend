from typing import Any, Literal, TypedDict

from app.schemas.appointment import AppointmentCreate


class ClinicChatState(TypedDict, total=False):
    session_id: str
    message: str
    doctor_id: int | None
    appointment_date: Any
    appointment_time: Any
    patient: AppointmentCreate | None
    conversation: dict[str, Any]
    long_term_memories: list[str]
    history: list[dict[str, Any]]
    summary: str
    intent: Literal["doctor_bio", "availability", "booking", "faq", "medical_web", "fallback"]
    response: str
    data: dict[str, Any]
    chunks: list[dict[str, Any]] | None
