"""Doctor availability requests and free-slot responses."""

from datetime import date as Date
from datetime import time as Time

from pydantic import BaseModel


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

