"""Doctor schedule payloads (create, update, out) plus doctor attributes."""

from datetime import date as Date
from datetime import time as Time

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import valid_image_value


class DoctorScheduleBase(BaseModel):
    doctor_name: str = Field(..., min_length=2)
    specialization: str | None = None
    photo_url: str | None = Field(default=None, max_length=200_000)
    start_time: Time
    end_time: Time
    break_start: Time | None = None
    break_end: Time | None = None
    leave_date: Date | None = None
    slot_duration: int = Field(default=30, ge=5, le=240)
    # Optional normalized ``doctor`` attributes, captured when a doctor is created.
    license_number: str | None = Field(default=None, max_length=64)
    qualification: str | None = Field(default=None, max_length=200)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    bio: str | None = None
    consultation_fee: float | None = Field(default=None, ge=0)
    consultation_duration: int | None = Field(default=None, ge=5, le=240)
    is_verified: bool = False

    @field_validator("photo_url")
    @classmethod
    def photo_policy(cls, value: str | None) -> str | None:
        return valid_image_value(value)

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
    photo_url: str | None = Field(default=None, max_length=200_000)
    start_time: Time | None = None
    end_time: Time | None = None
    break_start: Time | None = None
    break_end: Time | None = None
    leave_date: Date | None = None
    slot_duration: int | None = Field(default=None, ge=5, le=240)
    # Optional normalized ``doctor`` attributes.
    license_number: str | None = Field(default=None, max_length=64)
    qualification: str | None = Field(default=None, max_length=200)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    bio: str | None = None
    consultation_fee: float | None = Field(default=None, ge=0)
    consultation_duration: int | None = Field(default=None, ge=5, le=240)
    is_verified: bool | None = None

    @field_validator("photo_url")
    @classmethod
    def photo_policy(cls, value: str | None) -> str | None:
        return valid_image_value(value)



class DoctorScheduleOut(DoctorScheduleBase):
    """A doctor plus their working-hours row.

    ``id`` and ``doctor_id`` are the doctor's id (the bookable identity); the
    schedule row's own key is exposed as ``schedule_id``.
    """

    id: int
    doctor_id: int
    schedule_id: int

