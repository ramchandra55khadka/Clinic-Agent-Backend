"""User account and profile repositories."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.patient import Patient
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile
from app.schemas.user_auth import UserRegister
from app.schemas.user_profile import UserProfileUpdate


def get_user_by_email(db: Session, email: str):
    return db.query(UserAccount).filter(UserAccount.email == email.lower()).first()


def get_user_by_id(db: Session, user_id: str):
    return db.query(UserAccount).filter(UserAccount.id == user_id).first()


def create_user_account(db: Session, user: UserRegister, password_hash: str, role: str = "patient"):
    """Creates an account: an identity row, a profile (name/phone) and credentials.

    Public registration always passes the default ``patient`` (which also gets a
    ``patient`` row); staff/admin accounts are created by an administrator or the CLI.
    """
    db_user = UserAccount(
        email=str(user.email).lower(),
        role=role,
        is_active=True,
        password_hash=password_hash,
    )
    db.add(db_user)
    db.flush()

    profile = UserProfile(
        user_id=db_user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
    )
    db.add(profile)
    db.flush()

    if role == "patient":
        db.add(Patient(profile_id=profile.id))

    db.commit()
    db.refresh(db_user)
    return db_user


def update_user_profile(db: Session, user: UserAccount, payload: UserProfileUpdate):
    """Applies profile edits (name/phone/photo) to the account's ``user_profile``."""
    profile = user.profile
    if profile is None:
        profile = UserProfile(user_id=user.id, first_name=user.first_name or user.email, last_name=user.last_name)
        db.add(profile)
        db.flush()

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)

    db.commit()
    db.refresh(user)
    return user


def register_successful_login(db: Session, user: UserAccount) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    db.commit()


def register_failed_login(db: Session, user: UserAccount, max_attempts: int, lockout_minutes: int) -> int:
    """Increments the failure counter and locks the account once it is reached."""
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= max_attempts:
        user.locked_until = datetime.now(UTC) + timedelta(minutes=lockout_minutes)
    db.commit()
    return user.failed_login_attempts


def is_locked(user: UserAccount) -> bool:
    locked_until = user.locked_until
    if locked_until is None:
        return False
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > datetime.now(UTC)


def update_password_hash(db: Session, user: UserAccount, password_hash: str) -> None:
    user.password_hash = password_hash
    user.password_changed_at = datetime.now(UTC)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()


def set_user_role(db: Session, user: UserAccount, role: str):
    user.role = role
    db.commit()
    db.refresh(user)
    return user


def set_user_active(db: Session, user: UserAccount, is_active: bool):
    user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user


def delete_user_account(db: Session, user: UserAccount) -> None:
    db.delete(user)
    db.commit()


def get_all_users(db: Session, *, role: str | None = None) -> list[UserAccount]:
    """Every account, newest first, optionally filtered by role."""
    query = db.query(UserAccount)
    if role:
        query = query.filter(UserAccount.role == role)
    return query.order_by(UserAccount.id).all()


def count_active_admins(db: Session, *, exclude_user_id: str | None = None) -> int:
    """Used to refuse changes that would lock everyone out of administration."""
    query = db.query(UserAccount).filter(
        UserAccount.role == "admin",
        UserAccount.is_active.is_(True),
    )
    if exclude_user_id is not None:
        query = query.filter(UserAccount.id != exclude_user_id)
    return query.count()
