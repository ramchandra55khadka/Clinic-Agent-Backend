"""Reusable education-history fields.

This abstract model is not mapped to a table; concrete subclasses (such as
:class:`~app.models.doctor_education.DoctorEducation`) inherit its
columns and add their own foreign key.
"""

from sqlalchemy import Column, Date, DateTime, Integer, String, Text, func

from app.db.base import Base


class BaseEducation(Base):
    __abstract__ = True

    id = Column(Integer, primary_key=True)

    degree = Column(String(150), nullable=False)
    institution = Column(String(200), nullable=False)
    field_of_study = Column(String(150), nullable=True)

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
