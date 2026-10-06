"""Data-access layer — one module per aggregate.

Import a specific function from the module that owns it, e.g.
``from app.repositories.user import get_user_by_email``. The re-exports below also
let callers treat the package as a single namespace: ``from app import repositories``.
"""

from app.repositories.appointment import (
    create_appointment,
    get_all_appointments,
    get_appointment,
    get_appointments_by_doctor,
    get_appointments_by_email,
    get_appointments_for_user,
    owns_appointment,
    update_appointment,
)
from app.repositories.audit_log import log_audit
from app.repositories.doctor import (
    create_doctor_schedule,
    delete_doctor_schedule,
    get_all_doctor_schedules,
    get_doctor,
    get_doctor_schedule,
    update_doctor_schedule,
)
from app.repositories.patient import ensure_patient_for_user, get_patient_by_email
from app.repositories.refresh_token import (
    create_refresh_token,
    get_refresh_token,
    revoke_refresh_token,
    revoke_user_refresh_tokens,
    rotate_refresh_token,
)
from app.repositories.user import (
    count_active_admins,
    create_user_account,
    create_user_profile,
    delete_user_account,
    get_all_users,
    get_profile_by_user_id,
    get_user_by_email,
    get_user_by_id,
    is_locked,
    register_failed_login,
    register_successful_login,
    set_user_active,
    set_user_role,
    update_password_hash,
    update_user_profile,
    user_out,
)

__all__ = [
    "count_active_admins",
    "create_appointment",
    "create_doctor_schedule",
    "create_refresh_token",
    "create_user_account",
    "create_user_profile",
    "delete_doctor_schedule",
    "delete_user_account",
    "ensure_patient_for_user",
    "get_all_appointments",
    "get_all_doctor_schedules",
    "get_all_users",
    "get_appointment",
    "get_appointments_by_doctor",
    "get_appointments_by_email",
    "get_appointments_for_user",
    "get_doctor",
    "get_doctor_schedule",
    "get_patient_by_email",
    "get_profile_by_user_id",
    "get_refresh_token",
    "get_user_by_email",
    "get_user_by_id",
    "is_locked",
    "log_audit",
    "owns_appointment",
    "register_failed_login",
    "register_successful_login",
    "revoke_refresh_token",
    "revoke_user_refresh_tokens",
    "rotate_refresh_token",
    "set_user_active",
    "set_user_role",
    "update_appointment",
    "update_doctor_schedule",
    "update_password_hash",
    "update_user_profile",
    "user_out",
]
