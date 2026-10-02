"""Authentication and authorization dependencies.

``get_current_user`` verifies the bearer token; ``require_staff``/``require_admin``
add role checks (see :mod:`app.core.roles`). Every protected route depends on one
of these, so the backend — not the frontend — is the source of truth for who may
do what.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import repositories
from app.core.roles import is_admin, is_staff
from app.db.session import get_db
from app.models.user_account import UserAccount
from app.services.auth import TokenError, decode_access_token

security = HTTPBearer(auto_error=False)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


def client_ip(request: Request) -> str | None:
    """Best-effort caller IP.

    ``X-Forwarded-For`` is only meaningful behind a trusted reverse proxy; the
    left-most entry is used because that is the original client. Deployments
    exposed directly to the internet should ignore the header instead.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> UserAccount:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers=_UNAUTHORIZED_HEADERS,
        )

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = str(payload["sub"])
    except (TokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers=_UNAUTHORIZED_HEADERS,
        ) from exc

    user = repositories.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or missing user",
            headers=_UNAUTHORIZED_HEADERS,
        )
    return user


def require_admin(current_user: UserAccount = Depends(get_current_user)) -> UserAccount:
    """Account management only: admin role required."""
    if not is_admin(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def require_staff(current_user: UserAccount = Depends(get_current_user)) -> UserAccount:
    """Clinic operations (doctors, availability): staff *or* admin."""
    if not is_staff(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinic staff access required",
        )
    return current_user


def require_roles(*roles: str):
    """Dependency factory: allows any of ``roles`` (admins always pass)."""
    allowed = set(roles)

    def dependency(current_user: UserAccount = Depends(get_current_user)) -> UserAccount:
        if current_user.role not in allowed and not is_admin(current_user.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return dependency


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> UserAccount | None:
    """Like :func:`get_current_user`, but a missing/invalid token yields ``None``.

    Used by endpoints that must stay usable with an expired access token — for
    example logout, which still has to revoke the refresh token.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None

    try:
        payload = decode_access_token(credentials.credentials)
        user = repositories.get_user_by_id(db, str(payload["sub"]))
    except (TokenError, KeyError, TypeError, ValueError):
        return None

    return user if user and user.is_active else None
