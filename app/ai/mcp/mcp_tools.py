"""MCP-style tools that the LangGraph chat workflow calls.

Booking delegates to `app.services.appointments` so the API and the agent apply
exactly the same rules (past slots, availability, double-booking).
"""

from datetime import date as Date
from datetime import time as Time
from typing import Any

from app.database.database import SessionLocal
from app.database.schema import AppointmentCreate
from app.services.appointments import BookingError
from app.services.appointments import book_appointment as book_appointment_record
from app.services.availability import explain_unavailability, get_available_slots
from app.services.email_scheduler import send_confirmation_for_appointment_id


def check_slots(doctor_id: int, appointment_date: Date) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        return get_available_slots(db, doctor_id, appointment_date)


def explain_slot(doctor_id: int, appointment_date: Date, appointment_time: Time) -> str | None:
    with SessionLocal() as db:
        return explain_unavailability(db, doctor_id, appointment_date, appointment_time)


def book_appointment(appointment: AppointmentCreate) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            saved = book_appointment_record(db, appointment)
        except BookingError as exc:
            return {"status": "failed", "reason": exc.reason, "message": exc.message}
        appointment_id = saved.id

    email_status = send_confirmation_for_appointment_id(appointment_id)
    return {
        "status": "success",
        "appointment": {
            "id": appointment_id,
            "patient_name": appointment.patient_name,
            "date": str(appointment.date),
            "time": str(appointment.time),
            "email_status": email_status,
        },
    }
