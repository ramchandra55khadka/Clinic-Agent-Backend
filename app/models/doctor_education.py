"""A doctor's education history.

Inherits every field from :class:`~app.models.base_education.BaseEducation`
and links each row to a :class:`~app.models.doctor.Doctor`.
"""

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.models.base_education import BaseEducation


class DoctorEducation(BaseEducation):
    __tablename__ = "doctor_education"

    doctor_id = Column(
        Integer,
        ForeignKey("doctor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    doctor = relationship("Doctor", back_populates="educations")
