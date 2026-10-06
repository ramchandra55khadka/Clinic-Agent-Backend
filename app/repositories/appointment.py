"""Appointment repositories."""

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.user_account import UserAccount
from app.repositories.patient import get_patient_by_email
from app.schemas.appointment import AppointmentCreate


def create_appointment(db: Session, appointment: AppointmentCreate, commit: bool = True):
    payload = appointment.model_dump() if hasattr(appointment, "model_dump") else dict(appointment)
    db_appointment = Appointment(**payload)
    # Link the normalized patient when the booking email matches an account.
    if db_appointment.patient_id is None:
        patient = get_patient_by_email(db, db_appointment.email)
        if patient is not None:
            db_appointment.patient_id = patient.id
    db.add(db_appointment)
    if commit:
        db.commit()
        db.refresh(db_appointment)
    else:
        db.flush()
    return db_appointment


def get_appointments_by_doctor(db: Session, doctor_id: int):
    return db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id
    ).all()


def get_all_appointments(db: Session):
    """Clinic-wide tracking list for staff and admins: every appointment,
    newest date first (mirrors the ordering of :func:`get_appointments_by_email`)."""
    return (
        db.query(Appointment)
        .order_by(Appointment.date.desc(), Appointment.time.desc())
        .all()
    )


def get_appointment(db: Session, appointment_id: int):
    return db.query(Appointment).filter(Appointment.id == appointment_id).first()


def get_appointments_by_email(db: Session, email: str):
    """Every appointment booked with this email — the patient's own history.

    Appointments store the patient's contact details rather than a user id, so the
    email is the ownership anchor (compared case-insensitively).
    """
    return (
        db.query(Appointment)
        .filter(func.lower(Appointment.email) == email.strip().lower())
        .order_by(Appointment.date.desc(), Appointment.time.desc())
        .all()
    )


def get_appointments_for_user(db: Session, user: UserAccount):
    """Every appointment the account tracks, newest date first.

    Ownership is account-based: bookings linked to the account's ``patient`` row
    (chat bookings are linked at write time) are returned regardless of which
    email was typed during booking. Bookings made with the account's own email
    are included too so rows from before linking existed stay visible.
    """
    patient = get_patient_by_email(db, user.email)
    condition = func.lower(Appointment.email) == (user.email or "").strip().lower()
    if patient is not None:
        condition = or_(Appointment.patient_id == patient.id, condition)
    return (
        db.query(Appointment)
        .filter(condition)
        .order_by(Appointment.date.desc(), Appointment.time.desc())
        .all()
    )


def owns_appointment(db: Session, user: UserAccount, appointment: Appointment | None) -> bool:
    """Account-based ownership: linked to the account's ``patient`` row, or
    booked with the account's own email (legacy rows predating the link)."""
    if appointment is None:
        return False
    if (appointment.email or "").strip().lower() == (user.email or "").strip().lower():
        return True
    patient = get_patient_by_email(db, user.email)
    return patient is not None and appointment.patient_id == patient.id


def update_appointment(db: Session, appointment: Appointment, changes: dict):
    """Applies ``changes`` and commits. Constraint violations propagate to the caller."""
    for key, value in changes.items():
        setattr(appointment, key, value)
    db.commit()
    db.refresh(appointment)
    return appointment
