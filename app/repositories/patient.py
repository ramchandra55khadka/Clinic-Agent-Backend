"""Patient repositories."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.patient import Patient
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile


def get_patient_by_email(db: Session, email: str):
    """The ``patient`` row whose account email matches (case-insensitive), if any."""
    if not email:
        return None
    return (
        db.query(Patient)
        .join(UserProfile, Patient.profile_id == UserProfile.id)
        .join(UserAccount, UserProfile.user_id == UserAccount.id)
        .filter(func.lower(UserAccount.email) == email.strip().lower())
        .first()
    )


def ensure_patient_for_user(db: Session, user: UserAccount) -> Patient:
    """Returns the account's ``patient`` row, creating it (and a profile) when missing.

    The profile is looked up by ``user_id`` and the patient row by ``profile_id``
    rather than through ORM relationships: account, profile and role rows are
    created and read separately (see ``app.models.user_account``), and
    ``UserProfile`` exposes no reverse ``patient`` attribute.
    """
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if profile is None:
        profile = UserProfile(user_id=user.id, email=user.email, first_name=user.email)
        db.add(profile)
        db.flush()

    patient = db.query(Patient).filter(Patient.profile_id == profile.id).first()
    if patient is None:
        patient = Patient(profile_id=profile.id)
        db.add(patient)
        db.commit()
        db.refresh(patient)

    return patient
