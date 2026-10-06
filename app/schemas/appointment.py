"""Appointment booking payloads (create, update, out)."""

from datetime import date as Date
from datetime import time as Time

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AppointmentCreate(BaseModel):
    doctor_id: int
    patient_name: str = Field(..., min_length=2)
    age: int = Field(..., ge=0, le=130)
    sex: str = Field(..., min_length=1)
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=30)
    date: Date
    time: Time



class AppointmentOut(AppointmentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str = "confirmed"
    confirmation_email_status: str = "pending"



class AppointmentUpdate(BaseModel):
    """Self-service edit of an appointment. The email is an immutable
    per-appointment snapshot (confirmation emails go there) and cannot be
    changed here; ownership resolves through the account's patient link."""

    patient_name: str | None = Field(default=None, min_length=2)
    age: int | None = Field(default=None, ge=0, le=130)
    sex: str | None = Field(default=None, min_length=1)
    phone: str | None = Field(default=None, min_length=7, max_length=30)
    date: Date | None = None
    time: Time | None = None

