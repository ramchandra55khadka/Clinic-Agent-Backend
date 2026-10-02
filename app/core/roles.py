"""Account roles — the single source of truth for who may do what.

Three roles exist:

``patient``
    A normal user. Books visits and manages their own appointments
    (``/appointments/me*``). This is what public registration always creates.
``staff``
    Clinic staff (front desk / reception). Maintains doctors and their
    availability — working hours, lunch break, time off and slot length — and can
    see the clinic-wide appointment list. Cannot manage accounts.
``admin``
    Everything staff can do, plus account management (creating staff/admins,
    changing roles, deactivating accounts).

Admin is a superset of staff, so checks are expressed as *groups* rather than
exact matches: see :data:`CLINIC_STAFF` and :data:`ADMIN_ONLY`.
"""

from typing import Final, Literal

Role = Literal["patient", "staff", "admin"]

PATIENT: Final = "patient"
STAFF: Final = "staff"
ADMIN: Final = "admin"

#: Every role the system accepts, in ascending order of privilege.
ROLES: Final[tuple[str, ...]] = (PATIENT, STAFF, ADMIN)

#: Roles that may maintain doctors and their availability.
CLINIC_STAFF: Final[tuple[str, ...]] = (STAFF, ADMIN)

#: Roles that may manage accounts.
ADMIN_ONLY: Final[tuple[str, ...]] = (ADMIN,)

ROLE_LABELS: Final[dict[str, str]] = {
    PATIENT: "Patient",
    STAFF: "Clinic staff",
    ADMIN: "Administrator",
}


def is_valid_role(role: str | None) -> bool:
    return role in ROLES


def is_staff(role: str | None) -> bool:
    """True for staff *and* admins (admins can do everything staff can)."""
    return role in CLINIC_STAFF


def is_admin(role: str | None) -> bool:
    return role == ADMIN


def role_label(role: str | None) -> str:
    """Human-readable role name, falling back to the raw value."""
    if not role:
        return "Unknown"
    return ROLE_LABELS.get(role, role)
