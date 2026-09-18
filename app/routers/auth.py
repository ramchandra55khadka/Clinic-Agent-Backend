"""Authentication endpoints.

Password failures are counted per account (lockout) and the caller IP is rate
limited; access tokens are short-lived JWTs, refresh tokens are rotated on every
use and revoked on logout or password change; every outcome is audited.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.rate_limit import ip_key, rate_limit
from app.database import crud
from app.database.database import get_db
from app.database.models import UserAccount
from app.database.schema import (
    ChangePasswordRequest,
    MessageResponse,
    RefreshRequest,
    TokenResponse,
    UserAccountOut,
    UserLogin,
    UserRegister,
)
from app.dependencies.auth import (
    client_ip,
    get_current_user,
    get_current_user_optional,
    user_agent,
)
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
    crud.create_refresh_token(
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
    if crud.get_user_by_email(db, str(payload.email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = crud.create_user_account(db, payload, hash_password(payload.password))
    crud.log_audit(
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
    user = crud.get_user_by_email(db, str(payload.email))
    if user is None or not user.is_active:
        # Identical message for unknown user and wrong password: no enumeration.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    user_auth = crud.get_user_auth(db, user.id)
    if user_auth is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if crud.is_locked(user_auth):
        crud.log_audit(
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

    if not verify_password(payload.password, user_auth.password_hash):
        attempts = crud.register_failed_login(
            db, user_auth, settings.max_failed_login_attempts, settings.lockout_minutes
        )
        crud.log_audit(
            db,
            action="auth.login_failed",
            actor=user,
            client_ip=client_ip(request),
            user_agent=user_agent(request),
            detail=f"failed attempts: {attempts}",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    crud.register_successful_login(db, user_auth)
    crud.log_audit(
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
    token = crud.get_refresh_token(db, hash_refresh_token(payload.refresh_token))
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = crud.get_user_by_id(db, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user")

    if token.revoked_at is not None:
        # Presenting an already-rotated token means the value leaked: revoke all.
        revoked = crud.revoke_user_refresh_tokens(db, user.id)
        crud.log_audit(
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
    crud.rotate_refresh_token(
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
        token = crud.get_refresh_token(db, hash_refresh_token(payload.refresh_token))
        if token is not None and token.revoked_at is None:
            crud.revoke_refresh_token(db, token)
            revoked = 1
    elif current_user is not None:
        revoked = crud.revoke_user_refresh_tokens(db, current_user.id)

    if current_user is not None:
        crud.log_audit(
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
    user_auth = crud.get_user_auth(db, current_user.id)
    if user_auth is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account credentials not found")

    if not verify_password(payload.current_password, user_auth.password_hash):
        crud.log_audit(
            db,
            action="auth.password_change_failed",
            actor=current_user,
            client_ip=client_ip(request),
            user_agent=user_agent(request),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    crud.update_password_hash(db, user_auth, hash_password(payload.new_password))
    revoked = crud.revoke_user_refresh_tokens(db, current_user.id)
    crud.log_audit(
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