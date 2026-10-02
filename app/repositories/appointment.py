"""Appointment repositories."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
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


def update_appointment(db: Session, appointment: Appointment, changes: dict):
    """Applies ``changes`` and commits. Constraint violations propagate to the caller."""
    for key, value in changes.items():
        setattr(appointment, key, value)
    db.commit()
    db.refresh(appointment)
    return appointment
