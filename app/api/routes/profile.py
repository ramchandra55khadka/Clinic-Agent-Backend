"""Profile endpoints.

The profile holds a user's personal data — name, contact details and the
optional ``date_of_birth``/``gender``/``address`` fields. It is deliberately
decoupled from the login account: ``POST /api/auth/register`` creates the
account (email + password), and this module creates/edits the matching profile.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import repositories
from app.api.deps import client_ip, get_current_user, user_agent
from app.db.session import get_db
from app.models.user_account import UserAccount
from app.schemas.user_profile import UserProfileCreate, UserProfileOut

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.post("", response_model=UserProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: UserProfileCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Creates the profile for the signed-in account.

    The profile's ``email`` is copied from the account; it is never supplied by
    the client. Patients also get their ``patient`` row here, so booking works
    right after onboarding.
    """
    if repositories.get_profile_by_user_id(db, current_user.id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists")

    profile = repositories.create_user_profile(db, current_user, payload)
    repositories.log_audit(
        db,
        action="user.profile_created",
        actor=current_user,
        entity="user",
        entity_id=current_user.id,
        client_ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return profile


@router.get("/me", response_model=UserProfileOut)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """The signed-in account's profile, or ``404`` when it has not been created yet."""
    profile = repositories.get_profile_by_user_id(db, current_user.id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile
