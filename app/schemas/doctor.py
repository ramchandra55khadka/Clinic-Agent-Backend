"""Doctor schedule payloads (create, update, out) plus doctor attributes."""

from datetime import date as Date
from datetime import time as Time

from pydantic import BaseModel, Field, computed_field, field_validator

from app.core.days import WEEKDAYS, normalize_days
from app.schemas.common import valid_image_value
from app.schemas.user_profile import GENDER_OPTIONS


class DoctorScheduleBase(BaseModel):
    # UserProfile fields
    first_name: str = Field(..., min_length=1)
    last_name: str | None = None
    email: str | None = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = None
    date_of_birth: Date | None = None
    gender: str | None = Field(default=None, pattern=f"^({'|'.join(GENDER_OPTIONS)})$")
    address: str | None = None
    photo_url: str | None = Field(default=None, max_length=8_000_000)

    # Doctor fields
    license_number: str | None = Field(default=None, max_length=64)
    specialization: str | None = None
    qualification: str | None = Field(default=None, max_length=200)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    bio: str | None = None
    consultation_fee: float | None = Field(default=None, ge=0)
    consultation_duration: int | None = Field(default=None, ge=5, le=240)
    is_verified: bool = False

    # DoctorSchedule fields
    start_time: Time
    end_time: Time
    break_start: Time | None = None
    break_end: Time | None = None
    leave_date: Date | None = None
    slot_duration: int = Field(default=30, ge=5, le=240)
    #: Weekdays the hours apply to; ``None`` means every day (legacy rows).
    days: list[str] | None = Field(default=None, max_length=len(WEEKDAYS))

    @field_validator("days")
    @classmethod
    def valid_days(cls, value: list[str] | None) -> list[str] | None:
        return normalize_days(value)

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

    @computed_field
    @property
    def doctor_name(self) -> str:
        """Computed full name for backward compatibility."""
        return " ".join(part for part in (self.first_name, self.last_name) if part)


class DoctorEducationBase(BaseModel):
    degree: str = Field(..., min_length=1, max_length=150)
    institution: str = Field(..., min_length=1, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=150)
    start_date: Date | None = None
    end_date: Date | None = None
    description: str | None = None

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, value: Date | None, info):
        start_date = info.data.get("start_date")
        if value and start_date and value < start_date:
            raise ValueError("end_date must be after start_date")
        return value


class DoctorEducationOut(DoctorEducationBase):
    id: int


class DoctorScheduleCreate(DoctorScheduleBase):
    educations: list[DoctorEducationBase] = Field(default_factory=list)



class DoctorScheduleUpdate(BaseModel):
    # UserProfile fields
    first_name: str | None = Field(default=None, min_length=1)
    last_name: str | None = None
    email: str | None = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = None
    date_of_birth: Date | None = None
    gender: str | None = Field(default=None, pattern=f"^({'|'.join(GENDER_OPTIONS)})$")
    address: str | None = None
    photo_url: str | None = Field(default=None, max_length=8_000_000)

    # Doctor fields
    license_number: str | None = Field(default=None, max_length=64)
    specialization: str | None = None
    qualification: str | None = Field(default=None, max_length=200)
    experience_years: int | None = Field(default=None, ge=0, le=80)
    bio: str | None = None
    consultation_fee: float | None = Field(default=None, ge=0)
    consultation_duration: int | None = Field(default=None, ge=5, le=240)
    is_verified: bool | None = None

    # DoctorSchedule fields
    start_time: Time | None = None
    end_time: Time | None = None
    break_start: Time | None = None
    break_end: Time | None = None
    leave_date: Date | None = None
    slot_duration: int | None = Field(default=None, ge=5, le=240)
    days: list[str] | None = Field(default=None, max_length=len(WEEKDAYS))
    educations: list[DoctorEducationBase] | None = None

    @field_validator("days")
    @classmethod
    def valid_days(cls, value: list[str] | None) -> list[str] | None:
        return normalize_days(value)

    @field_validator("photo_url")
    @classmethod
    def photo_policy(cls, value: str | None) -> str | None:
        return valid_image_value(value)

    @property
    def doctor_name(self) -> str | None:
        """Computed full name for backward compatibility."""
        if self.first_name is None and self.last_name is None:
            return None
        return " ".join(part for part in (self.first_name, self.last_name) if part)



class DoctorScheduleOut(DoctorScheduleBase):
    """A doctor plus their working-hours row.

    ``id`` and ``doctor_id`` are the doctor's id (the bookable identity); the
    schedule row's own key is exposed as ``schedule_id``.
    """

    id: int
    doctor_id: int
    schedule_id: int
    educations: list[DoctorEducationOut] = Field(default_factory=list)
