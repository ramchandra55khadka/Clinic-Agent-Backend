"""Login identity and credentials.

``user_account`` holds everything needed to authenticate and authorize: the
email, the role, the active flag and the password credential (merged in from the
old ``user_auth`` table, which was a strict 1:1 and carried no value as a
separate table). Personal data (name, phone, photo) lives in
:class:`~app.models.user_profile.UserProfile`. The convenience properties
below read through to the profile so API schemas can keep a flat shape.

``password_hash`` is nullable on purpose: an account created by an
administrator or the CLI has no password yet, so it cannot sign in until one is
set — mirroring the "no ``user_auth`` row" behaviour the old schema had.

:class:`RefreshToken` lives in this module too: it is the session table for the
same account, so all account-related rows are kept together.
"""

from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class UserAccount(Base):
    __tablename__ = "user_account"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, nullable=False, default="patient")
    is_active = Column(Boolean, nullable=False, default=True)

    # ------------------------------------------------------------------ #
    # Credentials + sign-in security state (formerly the user_auth table)
    # ------------------------------------------------------------------ #
    password_hash = Column(String, nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    profile = relationship(
        "UserProfile",
        back_populates="account",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # ------------------------------------------------------------------ #
    # Profile pass-throughs — keep the flat API shape (first_name/last_name/
    # phone/photo_url) so schemas can read a name straight off the account.
    # ------------------------------------------------------------------ #

    @property
    def first_name(self) -> str:
        return self.profile.first_name if self.profile else ""

    @property
    def last_name(self) -> str | None:
        return self.profile.last_name if self.profile else None

    @property
    def full_name(self) -> str:
        return self.profile.full_name if self.profile else ""

    @property
    def phone(self) -> str | None:
        return self.profile.phone if self.profile else None

    @property
    def photo_url(self) -> str | None:
        return self.profile.photo_url if self.profile else None

    @property
    def memory_enabled(self) -> bool:
        return True if self.profile is None else bool(self.profile.memory_enabled)

    @property
    def patient(self):
        """The ``Patient`` row linked through this account's profile, if any."""
        return self.profile.patient if self.profile else None

    @property
    def doctor(self):
        """The ``Doctor`` row linked through this account's profile, if any."""
        return self.profile.doctor if self.profile else None


class RefreshToken(Base):
    """A stored refresh-token session belonging to a :class:`UserAccount`.

    A refresh token is stored only as a SHA-256 hash. Rotation keeps a chain
    (``replaced_by_id``): presenting an already-rotated token means the value
    leaked, so the whole chain is revoked.
    """

    __tablename__ = "refresh_token"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(36), ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by_id = Column(Integer, ForeignKey("refresh_token.id"), nullable=True)
    user_agent = Column(String, nullable=True)
    client_ip = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
