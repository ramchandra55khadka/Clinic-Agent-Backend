"""MCP-style tools that the LangGraph chat workflow calls.

Booking delegates to `app.services.appointments` so the API and the agent apply
exactly the same rules (past slots, availability, double-booking).
"""

from datetime import date as Date
from datetime import time as Time
from typing import Any

from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.user_profile import UserProfile
from app.schemas.appointment import AppointmentCreate
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


def list_doctor_availability(appointment_date: Date) -> list[dict[str, Any]]:
    """All doctors with their available slots for a date, from the database."""
    with SessionLocal() as db:
        schedules = (
            db.query(DoctorSchedule)
            .join(Doctor, DoctorSchedule.doctor_id == Doctor.id)
            .join(UserProfile, Doctor.profile_id == UserProfile.id)
            .order_by(UserProfile.first_name, UserProfile.last_name)
            .all()
        )
        result: list[dict[str, Any]] = []
        for schedule in schedules:
            slots = get_available_slots(db, schedule.doctor_id, appointment_date)
            available_slots = [slot for slot in slots if slot.get("available")]
            result.append(
                {
                    "doctor_id": schedule.doctor_id,
                    "doctor_name": schedule.doctor_name,
                    "specialization": schedule.specialization,
                    "photo_url": schedule.photo_url,
                    "date": str(appointment_date),
                    "available": bool(available_slots),
                    "available_slots": available_slots,
                    "slot_count": len(available_slots),
                    "reason": (
                        "doctor_on_leave"
                        if schedule.leave_date == appointment_date
                        else (
                            "not_working_day"
                            if appointment_date.strftime("%A") not in schedule.days
                            else None
                        )
                    ),
                }
            )
        return result


def list_doctors() -> list[dict[str, Any]]:
    """All doctors from the database for name resolution."""
    with SessionLocal() as db:
        schedules = (
            db.query(DoctorSchedule)
            .join(Doctor, DoctorSchedule.doctor_id == Doctor.id)
            .join(UserProfile, Doctor.profile_id == UserProfile.id)
            .order_by(UserProfile.first_name, UserProfile.last_name)
            .all()
        )
        return [
            {
                "doctor_id": schedule.doctor_id,
                "doctor_name": schedule.doctor_name,
                "specialization": schedule.specialization,
                "photo_url": schedule.photo_url,
            }
            for schedule in schedules
        ]
