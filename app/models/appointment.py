"""Booked visits.

An appointment links to a :class:`Doctor` and (best effort) to a :class:`Patient`.
The patient contact columns are kept as an immutable per-appointment snapshot:
they are what confirmation emails are sent to, what ownership checks compare
against, and they preserve history if the profile later changes. The unique
constraint on ``(doctor_id, date, time)`` is the last line of defence against a
double-booking when two requests race past the availability pre-check.
"""

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("doctor_id", "date", "time", name="uq_appointment_doctor_slot"),
        Index("ix_appointments_patient_id", "patient_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctor.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patient.id", ondelete="SET NULL"), nullable=True)
    patient_name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    sex = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    time = Column(Time, nullable=False)
    status = Column(String, nullable=False, default="confirmed")
    confirmation_email_status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    doctor = relationship("Doctor")
    patient = relationship("Patient", back_populates="appointments")
