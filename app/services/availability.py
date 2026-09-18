from datetime import date as Date
from datetime import datetime, timedelta
from datetime import time as Time

from sqlalchemy.orm import Session

from app.database.models import Appointment, DoctorSchedule


def _to_date(value: str | Date) -> Date:
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    return value


def _to_time(value: str | Time) -> Time:
    if isinstance(value, str):
        return datetime.strptime(value, "%H:%M").time()
    return value


def _overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and end_a > start_b


def explain_unavailability(db: Session, doctor_id: int, appointment_date, appointment_time) -> str | None:
    appointment_date = _to_date(appointment_date)
    appointment_time = _to_time(appointment_time)

    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.id == doctor_id).first()
    if not schedule:
        return "doctor_not_found"

    if schedule.leave_date == appointment_date:
        return "doctor_on_leave"

    duration = schedule.slot_duration or 30
    appt_start = datetime.combine(appointment_date, appointment_time)
    appt_end = appt_start + timedelta(minutes=duration)
    schedule_start = datetime.combine(appointment_date, schedule.start_time)
    schedule_end = datetime.combine(appointment_date, schedule.end_time)

    if appt_start < schedule_start:
        return "before_working_hours"
    if appt_end > schedule_end:
        return "after_working_hours"

    if schedule.break_start and schedule.break_end:
        break_start = datetime.combine(appointment_date, schedule.break_start)
        break_end = datetime.combine(appointment_date, schedule.break_end)
        if _overlaps(appt_start, appt_end, break_start, break_end):
            return "during_break"

    appointments = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date == appointment_date,
        Appointment.status != "cancelled",
    ).all()

    for appointment in appointments:
        existing_start = datetime.combine(appointment_date, appointment.time)
        existing_end = existing_start + timedelta(minutes=duration)
        if _overlaps(appt_start, appt_end, existing_start, existing_end):
            return "slot_booked"

    return None


def check_availability(db: Session, doctor_id: int, appointment_date, appointment_time) -> bool:
    return explain_unavailability(db, doctor_id, appointment_date, appointment_time) is None


def get_available_slots(db: Session, doctor_id: int, appointment_date) -> list[dict]:
    appointment_date = _to_date(appointment_date)
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.id == doctor_id).first()
    if not schedule:
        return []

    duration = schedule.slot_duration or 30
    cursor = datetime.combine(appointment_date, schedule.start_time)
    end = datetime.combine(appointment_date, schedule.end_time)
    slots: list[dict] = []

    while cursor + timedelta(minutes=duration) <= end:
        reason = explain_unavailability(db, doctor_id, appointment_date, cursor.time())
        slots.append({
            "time": cursor.time(),
            "available": reason is None,
            "reason": reason,
        })
        cursor += timedelta(minutes=duration)

    return slots
