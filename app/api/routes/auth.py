"""Authentication endpoints.

Password failures are counted per account (lockout) and the caller IP is rate
limited; access tokens are short-lived JWTs, refresh tokens are rotated on every
use and revoked on logout or password change; every outcome is audited.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import repositories
from app.api.deps import (
    client_ip,
    get_current_user,
    get_current_user_optional,
    require_admin,
    user_agent,
)
from app.core.config import settings
from app.core.rate_limit import ip_key, rate_limit
from app.core.roles import ADMIN, Role
from app.db.session import get_db
from app.models.user_account import UserAccount
from app.schemas.common import MessageResponse
from app.schemas.user_auth import (
    ChangePasswordRequest,
    ManagedUserCreate,
    RefreshRequest,
    TokenResponse,
    UserAccountOut,
    UserActiveUpdate,
    UserLogin,
    UserRegister,
    UserRoleUpdate,
)
from app.schemas.user_profile import UserProfileUpdate
from app.services.auth import (
    access_token_expires_in,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    is_expired,
    refresh_token_expiry,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

login_rate_limit = rate_limit(
    scope="auth.login",
    limit=settings.login_rate_limit,
    window_seconds=settings.login_rate_window_seconds,
    key=ip_key,
)
register_rate_limit = rate_limit(
    scope="auth.register",
    limit=settings.register_rate_limit,
    window_seconds=settings.register_rate_window_seconds,
    key=ip_key,
)


def _issue_tokens(db: Session, user: UserAccount, request: Request) -> TokenResponse:
    """Mints an access token plus a freshly rotated refresh token."""
    raw_refresh, token_hash = generate_refresh_token()
    repositories.create_refresh_token(
        db,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=refresh_token_expiry(),
        user_agent=user_agent(request),
        client_ip=client_ip(request),
    )
    access_token = create_access_token(str(user.id), {"email": user.email, "role": user.role})
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=access_token_expires_in(),
        user=user,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    payload: UserRegister,
    request: Request,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(register_rate_limit),
):
    if repositories.get_user_by_email(db, str(payload.email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = repositories.create_user_account(db, payload, hash_password(payload.password))
    repositories.log_audit(
        db,
        action="user.registered",
        actor=user,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return _issue_tokens(db, user, request)


@router.post("/login", response_model=TokenResponse)
def login_user(
    payload: UserLogin,
    request: Request,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(login_rate_limit),
):
    user = repositories.get_user_by_email(db, str(payload.email))
    # No enumeration: unknown user, inactive user and password-less account all
    # get the identical failure (an account created without credentials cannot
    # sign in — this replaces the old "no user_auth row" check).
    if user is None or not user.is_active or user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if repositories.is_locked(user):
        repositories.log_audit(
            db,
            action="auth.login_locked",
            actor=user,
            client_ip=client_ip(request),
            user_agent=user_agent(request),
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account temporarily locked after repeated failed sign-ins.",
            headers={"Retry-After": str(settings.lockout_minutes * 60)},
        )

    if not verify_password(payload.password, user.password_hash):
        attempts = repositories.register_failed_login(
            db, user, settings.max_failed_login_attempts, settings.lockout_minutes
        )
        repositories.log_audit(
            db,
            action="auth.login_failed",
            actor=user,
            client_ip=client_ip(request),
            user_agent=user_agent(request),
            detail=f"failed attempts: {attempts}",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    repositories.register_successful_login(db, user)
    repositories.log_audit(
        db,
        action="auth.login_succeeded",
        actor=user,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return _issue_tokens(db, user, request)


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Rotates a refresh token: the presented token is revoked and replaced."""
    token = repositories.get_refresh_token(db, hash_refresh_token(payload.refresh_token))
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = repositories.get_user_by_id(db, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user")

    if token.revoked_at is not None:
        # Presenting an already-rotated token means the value leaked: revoke all.
        revoked = repositories.revoke_user_refresh_tokens(db, user.id)
        repositories.log_audit(
            db,
            action="auth.refresh_reuse_detected",
            actor=user,
            client_ip=client_ip(request),
            user_agent=user_agent(request),
            detail=f"revoked {revoked} session(s)",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token already used")

    if is_expired(token.expires_at):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    raw_refresh, token_hash = generate_refresh_token()
    repositories.rotate_refresh_token(
        db,
        token,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=refresh_token_expiry(),
        user_agent=user_agent(request),
        client_ip=client_ip(request),
    )
    return TokenResponse(
        access_token=create_access_token(str(user.id), {"email": user.email, "role": user.role}),
        refresh_token=raw_refresh,
        expires_in=access_token_expires_in(),
        user=user,
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    payload: RefreshRequest | None = None,
    current_user: UserAccount | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Revokes the presented refresh token — or every session of the caller."""
    revoked = 0
    if payload is not None:
        token = repositories.get_refresh_token(db, hash_refresh_token(payload.refresh_token))
        if token is not None and token.revoked_at is None:
            repositories.revoke_refresh_token(db, token)
            revoked = 1
    elif current_user is not None:
        revoked = repositories.revoke_user_refresh_tokens(db, current_user.id)

    if current_user is not None:
        repositories.log_audit(
            db,
            action="auth.logout",
            actor=current_user,
            client_ip=client_ip(request),
            user_agent=user_agent(request),
            detail=f"revoked {revoked} session(s)",
        )
    return MessageResponse(message="Signed out")


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    if current_user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account credentials not found")

    if not verify_password(payload.current_password, current_user.password_hash):
        repositories.log_audit(
            db,
            action="auth.password_change_failed",
            actor=current_user,
            client_ip=client_ip(request),
            user_agent=user_agent(request),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    repositories.update_password_hash(db, current_user, hash_password(payload.new_password))
    revoked = repositories.revoke_user_refresh_tokens(db, current_user.id)
    repositories.log_audit(
        db,
        action="auth.password_changed",
        actor=current_user,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
        detail=f"revoked {revoked} session(s)",
    )
    return MessageResponse(message="Password updated. Other devices must sign in again.")


@router.get("/me", response_model=UserAccountOut)
def get_me(current_user: UserAccount = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserAccountOut)
def update_me(
    payload: UserProfileUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    updated = repositories.update_user_profile(db, current_user, payload)
    repositories.log_audit(
        db,
        action="user.profile_updated",
        actor=updated,
        entity="user",
        entity_id=updated.id,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return updated


# --------------------------------------------------------------------------- #
# Account management (admin only)
#
# Public registration always creates patients. This is where clinic staff and
# administrators are onboarded, and where roles are changed or accounts are
# disabled.
#
# Authorization always reads the role from the database (see `get_current_user`),
# never from the JWT, so a role change takes effect on the very next request.
# Refresh tokens are revoked on every change so the account's other sessions
# cannot keep acting with the old role.
# --------------------------------------------------------------------------- #


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")


@router.get("/users", response_model=list[UserAccountOut])
def list_users(
    role: Role | None = None,
    db: Session = Depends(get_db),
    _admin: UserAccount = Depends(require_admin),
):
    """Every account, optionally filtered by role (newest first)."""
    return repositories.get_all_users(db, role=role)


@router.post("/users", response_model=UserAccountOut, status_code=status.HTTP_201_CREATED)
def create_managed_user(
    payload: ManagedUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: UserAccount = Depends(require_admin),
):
    """Creates a staff or admin account with a password chosen by the administrator."""
    if repositories.get_user_by_email(db, str(payload.email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = repositories.create_user_account(db, payload, hash_password(payload.password), role=payload.role)
    repositories.log_audit(
        db,
        action="user.created",
        actor=admin,
        entity="user",
        entity_id=user.id,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
        detail=f"role={user.role}",
    )
    return user


@router.patch("/users/{user_id}/role", response_model=UserAccountOut)
def update_user_role(
    user_id: str,
    payload: UserRoleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: UserAccount = Depends(require_admin),
):
    user = repositories.get_user_by_id(db, user_id)
    if user is None:
        raise _not_found()

    previous = user.role
    if previous == payload.role:
        return user

    # Never leave the clinic without an active administrator.
    if previous == ADMIN and payload.role != ADMIN and repositories.count_active_admins(db, exclude_user_id=user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active administrator must remain.",
        )

    repositories.set_user_role(db, user, payload.role)
    revoked = repositories.revoke_user_refresh_tokens(db, user.id)
    repositories.log_audit(
        db,
        action="user.role_changed",
        actor=admin,
        entity="user",
        entity_id=user.id,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
        detail=f"{previous} -> {payload.role}; revoked {revoked} session(s)",
    )
    return user


@router.patch("/users/{user_id}/active", response_model=UserAccountOut)
def update_user_active(
    user_id: str,
    payload: UserActiveUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: UserAccount = Depends(require_admin),
):
    """Enables or disables an account. Disabling signs the user out everywhere."""
    user = repositories.get_user_by_id(db, user_id)
    if user is None:
        raise _not_found()

    if user.id == admin.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account.",
        )

    if (
        not payload.is_active
        and user.role == ADMIN
        and repositories.count_active_admins(db, exclude_user_id=user.id) == 0
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active administrator must remain.",
        )

    repositories.set_user_active(db, user, payload.is_active)
    revoked = 0 if payload.is_active else repositories.revoke_user_refresh_tokens(db, user.id)
    repositories.log_audit(
        db,
        action="user.activated" if payload.is_active else "user.deactivated",
        actor=admin,
        entity="user",
        entity_id=user.id,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
        detail=f"revoked {revoked} session(s)",
    )
    return user

@router.delete("/users/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: UserAccount = Depends(require_admin),
):
    """Permanently deletes a team account. Protected against self-delete and last-admin removal."""
    user = repositories.get_user_by_id(db, user_id)
    if user is None:
        raise _not_found()

    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )

    if user.role == ADMIN and repositories.count_active_admins(db, exclude_user_id=user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active administrator must remain.",
        )

    deleted_user_id = user.id
    deleted_email = user.email
    deleted_role = user.role
    revoked = repositories.revoke_user_refresh_tokens(db, user.id)
    repositories.log_audit(
        db,
        action="user.deleted",
        actor=admin,
        entity="user",
        entity_id=deleted_user_id,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
        detail=f"deleted {deleted_email}; role={deleted_role}; revoked {revoked} session(s)",
    )
    repositories.delete_user_account(db, user)
    return MessageResponse(message="Account deleted")

