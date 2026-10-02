from datetime import date as Date
from datetime import time as Time

from pydantic import BaseModel

from app.schemas.appointment import AppointmentCreate


class MCPAvailabilityRequest(BaseModel):
    doctor_id: int
    date: Date
    time: Time | None = None


class MCPBookAppointmentRequest(BaseModel):
    appointment: AppointmentCreate
