from datetime import date as Date
from datetime import time as Time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.services.auth import password_problems


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=12)
    system_prompt: str | None = None


class QueryResponse(BaseModel):
    response: str
    chunks: list[dict[str, Any]] | None = None


class DoctorScheduleBase(BaseModel):
    doctor_name: str = Field(..., min_length=2)
    specialization: str | None = None
    start_time: Time
    end_time: Time
    break_start: Time | None = None
    break_end: Time | None = None
    leave_date: Date | None = None
    slot_duration: int = Field(default=30, ge=5, le=240)

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, value: Time, info):
        start_time = info.data.get("start_time")
        if start_time and value <= start_time:
            raise ValueError("end_time must be after start_time")
        return value

    @field_validator("break_end")
    @classmethod
    def break_end_after_start(cls, value: Time | None, info):
        break_start = info.data.get("break_start")
        if value and break_start and value <= break_start:
            raise ValueError("break_end must be after break_start")
        return value


class DoctorScheduleCreate(DoctorScheduleBase):
    pass


class DoctorScheduleUpdate(BaseModel):
    doctor_name: str | None = Field(default=None, min_length=2)
    specialization: str | None = None
    start_time: Time | None = None
    end_time: Time | None = None
    break_start: Time | None = None
    break_end: Time | None = None
    leave_date: Date | None = None
    slot_duration: int | None = Field(default=None, ge=5, le=240)


class DoctorScheduleOut(DoctorScheduleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


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


class AvailabilityRequest(BaseModel):
    doctor_id: int
    date: Date
    time: Time | None = None


class SlotOut(BaseModel):
    time: Time
    available: bool
    reason: str | None = None


class AvailabilityResponse(BaseModel):
    doctor_id: int
    date: Date
    available: bool
    reason: str | None = None
    slots: list[SlotOut] = []


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1)
    doctor_id: int | None = None
    appointment_date: Date | None = None
    appointment_time: Time | None = None
    patient: AppointmentCreate | None = None


class ChatResponse(BaseModel):
    session_id: str
    intent: Literal["doctor_bio", "availability", "booking", "fallback"]
    response: str
    data: dict[str, Any] = {}
    chunks: list[dict[str, Any]] | None = None


class UserRegister(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    phone: str | None = Field(default=None, min_length=7, max_length=30)

    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        problems = password_problems(value)
        if problems:
            raise ValueError("Password " + ", ".join(problems))
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        problems = password_problems(value)
        if problems:
            raise ValueError("Password " + ", ".join(problems))
        return value


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=16)


class UserAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: EmailStr
    phone: str | None = None
    role: str
    is_active: bool


class TokenResponse(BaseModel):
    """Issued tokens. The refresh token is stored httpOnly by the frontend BFF."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserAccountOut


class MessageResponse(BaseModel):
    message: str
