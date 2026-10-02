"""Personal profile shared by patients, doctors and staff.

A profile belongs to at most one login account (``user_id`` is unique) but may
also stand alone — for example a doctor record entered by clinic staff who does
not sign in.

Personal names are stored split into ``first_name``/``last_name``. Callers that
think in a single display string (doctor schedules, the MCP tool layer) can keep
using :attr:`UserProfile.full_name`, which composes the columns on read and
splits them on write — see :func:`split_display_name`.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.db.base import Base


def split_display_name(name: str | None) -> tuple[str, str | None]:
    """Split a single display name into ``(first_name, last_name)``.

    The last whitespace-separated token becomes the surname, so
    ``"Mary Jane Watson"`` becomes ``("Mary Jane", "Watson")``. A name with no
    separator stays whole (``("Madonna", None)``) and an empty or missing name
    yields ``("", None)``.
    """
    parts = (name or "").split()
    if not parts:
        return "", None
    if len(parts) == 1:
        return parts[0], None
    return " ".join(parts[:-1]), parts[-1]


def join_display_name(first_name: str | None, last_name: str | None) -> str:
    """Compose a display name from the stored parts, without stray whitespace."""
    return " ".join(part for part in (first_name, last_name) if part)


class UserProfile(Base):
    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        String(36),
        ForeignKey("user_account.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
        index=True,
    )
    first_name = Column(String, nullable=False, server_default="")
    last_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    photo_url = Column(Text, nullable=True)
    memory_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    account = relationship("UserAccount", back_populates="profile")
    doctor = relationship(
        "Doctor",
        back_populates="profile",
        uselist=False,
        cascade="all, delete-orphan",
    )
    patient = relationship(
        "Patient",
        back_populates="profile",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # ------------------------------------------------------------------ #
    # Display-name convenience: keeps single-string call sites (doctor_name,
    # appointment output) working on top of the two stored columns.
    # ------------------------------------------------------------------ #

    @property
    def full_name(self) -> str:
        return join_display_name(self.first_name, self.last_name)

    @full_name.setter
    def full_name(self, value: str | None) -> None:
        self.first_name, self.last_name = split_display_name(value)
