"""Patient-specific attributes, linked 1:1 to a :class:`UserProfile`.

The link is a one-way FK (``patient.profile_id``); ``UserProfile`` exposes no
reverse ``patient`` relationship, so look a patient row up by ``profile_id``
rather than off the profile.
"""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Patient(Base):
    __tablename__ = "patient"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(
        Integer,
        ForeignKey("user_profile.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String, nullable=True)
    blood_group = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    profile = relationship("UserProfile")
    appointments = relationship(
        "Appointment",
        back_populates="patient",
    )
