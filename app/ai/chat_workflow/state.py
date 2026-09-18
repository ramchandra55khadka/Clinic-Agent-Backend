from typing import Any, Literal, TypedDict

from app.database.schema import AppointmentCreate


class ClinicChatState(TypedDict, total=False):
    session_id: str
    message: str
    doctor_id: int | None
    appointment_date: Any
    appointment_time: Any
    patient: AppointmentCreate | None
    conversation: dict[str, Any]
    intent: Literal["doctor_bio", "availability", "booking", "fallback"]
    response: str
    data: dict[str, Any]
    chunks: list[dict[str, Any]] | None
