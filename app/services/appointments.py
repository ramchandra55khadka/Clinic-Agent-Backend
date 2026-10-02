"""Booking rules.

The availability pre-check produces good error messages, but the unique
constraint on ``(doctor_id, date, time)`` is what actually guarantees a slot
cannot be double-booked when two requests race. Email delivery happens outside
the request (router BackgroundTasks / MCP tool).
"""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import repositories
from app.core.config import settings
from app.models.appointment import Appointment
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate
from app.services.availability import explain_unavailability


class BookingError(Exception):
    """A booking was rejected: `reason` is machine-readable, `message` is for users."""

    def __init__(self, reason: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status_code = status_code


def is_in_the_past(appointment_date, appointment_time) -> bool:
    """True when the slot lies before "now" in the clinic's local timezone."""
    moment = datetime.combine(appointment_date, appointment_time, tzinfo=settings.clinic_tzinfo)
    return moment <= datetime.now(settings.clinic_tzinfo)


def book_appointment(db: Session, appointment: AppointmentCreate) -> Appointment:
    """Persists a booking or raises :class:`BookingError`."""
    if is_in_the_past(appointment.date, appointment.time):
        raise BookingError(
            "in_the_past",
            "That time has already passed. Please choose a later slot.",
        )

    reason = explain_unavailability(db, appointment.doctor_id, appointment.date, appointment.time)
    if reason is not None:
        raise BookingError(reason, f"That slot is not available ({reason.replace('_', ' ')}).")

    try:
        saved = repositories.create_appointment(db, appointment, commit=False)
        db.commit()
        db.refresh(saved)
    except IntegrityError as exc:
        # Lost the race against a concurrent booking: the constraint held.
        db.rollback()
        raise BookingError(
            "slot_taken",
            "That slot was just booked. Please choose another.",
            status_code=409,
        ) from exc

    return saved


def update_owned_appointment(
    db: Session,
    appointment: Appointment,
    payload: AppointmentUpdate,
) -> Appointment:
    """Applies a patient's own edits (details and/or reschedule).

    A moved appointment is validated exactly like a new booking, except that the
    appointment itself is excluded from the availability check.
    """
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        return appointment

    rescheduled = "date" in changes or "time" in changes
    if rescheduled:
        new_date = changes.get("date", appointment.date)
        new_time = changes.get("time", appointment.time)

        if is_in_the_past(new_date, new_time):
            raise BookingError(
                "in_the_past",
                "That time has already passed. Please choose a later slot.",
            )

        reason = explain_unavailability(
            db,
            appointment.doctor_id,
            new_date,
            new_time,
            exclude_appointment_id=appointment.id,
        )
        if reason is not None:
            raise BookingError(reason, f"That slot is not available ({reason.replace('_', ' ')}).")

    try:
        return repositories.update_appointment(db, appointment, changes)
    except IntegrityError as exc:
        db.rollback()
        raise BookingError(
            "slot_taken",
            "That slot was just booked. Please choose another.",
            status_code=409,
        ) from exc


def cancel_owned_appointment(db: Session, appointment: Appointment) -> Appointment:
    """Marks the appointment cancelled, which frees the slot for others."""
    if appointment.status == "cancelled":
        return appointment
    return repositories.update_appointment(db, appointment, {"status": "cancelled"})
