"""Doctor-specific attributes, linked 1:1 to a :class:`UserProfile`."""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Doctor(Base):
    __tablename__ = "doctor"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(
        Integer,
        ForeignKey("user_profile.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    license_number = Column(String(64), nullable=True)
    specialization = Column(String, nullable=True)
    qualification = Column(String, nullable=True)
    experience_years = Column(Integer, nullable=True)
    bio = Column(Text, nullable=True)
    consultation_fee = Column(Float, nullable=True)
    consultation_duration = Column(Integer, nullable=False, default=30)
    is_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    profile = relationship("UserProfile", back_populates="doctor")
    schedules = relationship(
        "DoctorSchedule",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
    educations = relationship(
        "DoctorEducation",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
