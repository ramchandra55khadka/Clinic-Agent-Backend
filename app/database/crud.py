from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.database.schema import AppointmentCreate, DoctorScheduleCreate, DoctorScheduleUpdate, UserRegister

from .models import Appointment, AuditLog, DoctorSchedule, RefreshToken, UserAccount, UserAuth

# -------------------- Doctor Schedule CRUD --------------------

def create_doctor_schedule(db: Session, schedule: DoctorScheduleCreate):
    db_schedule = DoctorSchedule(**schedule.model_dump())
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    return db_schedule


def get_doctor_schedule(db: Session, doctor_id: int):
    return db.query(DoctorSchedule).filter(
        DoctorSchedule.id == doctor_id
    ).first()

def get_all_doctor_schedules(db: Session):
    return db.query(DoctorSchedule).all()

def update_doctor_schedule(db: Session, doctor_id: int, schedule: DoctorScheduleUpdate):
    db_schedule = db.query(DoctorSchedule).filter(
        DoctorSchedule.id == doctor_id
    ).first()

    if not db_schedule:
        return None

    for key, value in schedule.model_dump(exclude_unset=True).items():
        setattr(db_schedule, key, value)

    db.commit()
    db.refresh(db_schedule)
    return db_schedule


def delete_doctor_schedule(db: Session, doctor_id: int):
    db_schedule = db.query(DoctorSchedule).filter(
        DoctorSchedule.id == doctor_id
    ).first()
    if not db_schedule:
        return False
    db.delete(db_schedule)
    db.commit()
    return True


# -------------------- Appointment CRUD --------------------

def create_appointment(db: Session, appointment: AppointmentCreate, commit: bool = True):
    payload = appointment.model_dump() if hasattr(appointment, "model_dump") else dict(appointment)
    db_appointment = Appointment(**payload)
    db.add(db_appointment)
    if commit:
        db.commit()
        db.refresh(db_appointment)
    else:
        db.flush()
    return db_appointment


def get_appointments_by_doctor(db: Session, doctor_id: int):
    return db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id
    ).all()


# -------------------- Authentication CRUD --------------------

def get_user_by_email(db: Session, email: str):
    return db.query(UserAccount).filter(UserAccount.email == email.lower()).first()


def get_user_by_id(db: Session, user_id: int):
    return db.query(UserAccount).filter(UserAccount.id == user_id).first()


def create_user_account(db: Session, user: UserRegister, password_hash: str):
    db_user = UserAccount(
        full_name=user.full_name,
        email=str(user.email).lower(),
        phone=user.phone,
        role="patient",
        is_active=True,
    )
    db.add(db_user)
    db.flush()

    db_auth = UserAuth(user_id=db_user.id, password_hash=password_hash)
    db.add(db_auth)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_user_auth(db: Session, user_id: int):
    return db.query(UserAuth).filter(UserAuth.user_id == user_id).first()


def register_successful_login(db: Session, user_auth: UserAuth) -> None:
    user_auth.failed_login_attempts = 0
    user_auth.locked_until = None
    user_auth.last_login_at = datetime.now(UTC)
    db.commit()


def register_failed_login(db: Session, user_auth: UserAuth, max_attempts: int, lockout_minutes: int) -> int:
    """Increments the failure counter and locks the account once it is reached."""
    from datetime import timedelta

    user_auth.failed_login_attempts = (user_auth.failed_login_attempts or 0) + 1
    if user_auth.failed_login_attempts >= max_attempts:
        user_auth.locked_until = datetime.now(UTC) + timedelta(minutes=lockout_minutes)
    db.commit()
    return user_auth.failed_login_attempts


def is_locked(user_auth: UserAuth) -> bool:
    locked_until = user_auth.locked_until
    if locked_until is None:
        return False
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > datetime.now(UTC)


def update_password_hash(db: Session, user_auth: UserAuth, password_hash: str) -> None:
    user_auth.password_hash = password_hash
    user_auth.password_changed_at = datetime.now(UTC)
    user_auth.failed_login_attempts = 0
    user_auth.locked_until = None
    db.commit()


def set_user_role(db: Session, user: UserAccount, role: str):
    user.role = role
    db.commit()
    db.refresh(user)
    return user


# -------------------- Refresh token CRUD --------------------

def create_refresh_token(
    db: Session,
    *,
    user_id: int,
    token_hash: str,
    expires_at: datetime,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        client_ip=client_ip,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def rotate_refresh_token(
    db: Session,
    token: RefreshToken,
    *,
    user_id: int,
    token_hash: str,
    expires_at: datetime,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> RefreshToken:
    """Issues the replacement token and marks the presented one as rotated."""
    replacement = create_refresh_token(
        db,
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        client_ip=client_ip,
    )
    token.revoked_at = datetime.now(UTC)
    token.replaced_by_id = replacement.id
    db.commit()
    return replacement


def get_refresh_token(db: Session, token_hash: str):
    return db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()


def revoke_refresh_token(db: Session, token: RefreshToken, replaced_by_id: int | None = None) -> None:
    token.revoked_at = datetime.now(UTC)
    token.replaced_by_id = replaced_by_id
    db.commit()


def revoke_user_refresh_tokens(db: Session, user_id: int) -> int:
    """Revokes every active refresh token of a user (used on password change)."""
    now = datetime.now(UTC)
    tokens = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .all()
    )
    for token in tokens:
        token.revoked_at = now
    db.commit()
    return len(tokens)


# -------------------- Audit log --------------------

def log_audit(
    db: Session,
    *,
    action: str,
    actor: UserAccount | None = None,
    actor_email: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    detail: str | None = None,
) -> None:
    """Records a security-relevant event. Never raises into the request path."""
    try:
        db.add(
            AuditLog(
                actor_id=actor.id if actor else None,
                actor_email=actor_email or (actor.email if actor else None),
                action=action,
                entity=entity,
                entity_id=None if entity_id is None else str(entity_id),
                client_ip=client_ip,
                user_agent=user_agent,
                detail=detail,
            )
        )
        db.commit()
    except Exception:  # pragma: no cover - auditing must not break requests
        db.rollback()
