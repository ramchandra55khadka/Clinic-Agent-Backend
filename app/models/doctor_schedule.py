"""Working hours, breaks and time off for a :class:`Doctor`.

A doctor may have several schedule rows (the model supports 1:N); the clinic UI
creates one working-hours row per doctor. Display fields such as ``doctor_name``,
``specialization`` and ``photo_url`` are read through the ``doctor``/``profile``
relationships so callers keep a flat view of "the doctor".
"""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Time, func
from sqlalchemy.orm import relationship

from app.core.days import column_to_days
from app.db.base import Base


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedule"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(
        Integer,
        ForeignKey("doctor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    break_start = Column(Time, nullable=True)
    break_end = Column(Time, nullable=True)
    leave_date = Column(Date, nullable=True)
    slot_duration = Column(Integer, default=30, nullable=False)
    #: Comma-separated weekday names this row applies to; ``NULL`` = every day
    #: (the behaviour of schedules written before working days existed).
    working_days = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    doctor = relationship("Doctor", back_populates="schedules")

    # ------------------------------------------------------------------ #
    # Read-through helpers: the doctor's identity now lives in
    # doctor / user_profile. These keep existing callers working.
    # ------------------------------------------------------------------ #

    @property
    def doctor_name(self) -> str:
        profile = self.doctor.profile if self.doctor else None
        return profile.full_name if profile else ""

    @property
    def specialization(self) -> str | None:
        return self.doctor.specialization if self.doctor else None

    @property
    def photo_url(self) -> str | None:
        profile = self.doctor.profile if self.doctor else None
        return profile.photo_url if profile else None

    @property
    def days(self) -> list[str]:
        """Weekdays this row applies to (all seven when unset)."""
        return column_to_days(self.working_days)
