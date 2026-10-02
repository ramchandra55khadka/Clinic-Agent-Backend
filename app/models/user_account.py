"""Login identity and credentials.

``user_account`` holds everything needed to authenticate and authorize: the
email, the role, the active flag and the password credential (merged in from the
old ``user_auth`` table, which was a strict 1:1 and carried no value as a
separate table).

Personal data (first/last name, phone, photo, memory flag) lives in
:class:`~app.models.user_profile.UserProfile`. The two rows are deliberately
**not** joined by an ORM relationship: they are created by separate calls
(account first, then profile) and are read back through explicit queries keyed
on ``user_profile.user_id`` / the copied ``user_profile.email``. Build the flat
API shape with :func:`app.repositories.user.user_out`.

``password_hash`` is nullable on purpose: an account created by an
administrator or the CLI has no password yet, so it cannot sign in until one is
set — mirroring the "no ``user_auth`` row" behaviour the old schema had.

:class:`RefreshToken` lives in this module too: it is the session table for the
same account, so all account-related rows are kept together.
"""

from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

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

    # The matching ``user_profile`` row is intentionally NOT a relationship:
    # account and profile are created and read separately (see the module
    # docstring). Use ``app.repositories.user.get_profile_by_user_id``. 


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
