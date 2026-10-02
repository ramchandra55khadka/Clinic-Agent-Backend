"""The three-role model: patient, staff and admin.

Doctors and their availability are maintained by clinic staff *or* an admin;
account management is admin-only; public registration always creates a patient.
"""

import pytest

from app import repositories
from app.cli import bootstrap_admin
from app.core.roles import ADMIN, PATIENT, ROLES, STAFF, is_staff
from app.db.session import SessionLocal
from app.models.audit_log import AuditLog

SCHEDULE_PAYLOAD = {
    "doctor_name": "Dr. Role Check",
    "specialization": "Dermatology",
    "start_time": "09:00:00",
    "end_time": "13:00:00",
    "slot_duration": 20,
}

# Endpoints only clinic staff (and therefore admins) may reach.
STAFF_ENDPOINTS = [
    ("POST", "/doctor-schedule/"),
    ("PUT", "/doctor-schedule/1"),
    ("DELETE", "/doctor-schedule/1"),
    ("GET", "/appointments/1"),
]

# Endpoints only administrators may reach.
ADMIN_ENDPOINTS = [
    ("GET", "/api/auth/users"),
    ("POST", "/api/auth/users"),
    ("PATCH", "/api/auth/users/1/role"),
    ("PATCH", "/api/auth/users/1/active"),
]


def test_role_constants_are_consistent():
    assert ROLES == (PATIENT, STAFF, ADMIN)
    assert is_staff(STAFF) and is_staff(ADMIN)
    assert not is_staff(PATIENT)


@pytest.mark.parametrize("method,path", STAFF_ENDPOINTS)
def test_patients_cannot_manage_doctors_or_see_clinic_wide_lists(
    client, make_user, method, path
):
    patient = make_user(role=PATIENT)
    response = client.request(method, path, headers=patient["headers"], json=SCHEDULE_PAYLOAD)
    assert response.status_code == 403, f"{method} {path} returned {response.status_code}"
    assert "staff" in response.json()["detail"].lower()


def test_staff_can_create_and_update_a_doctor_schedule(client, make_user):
    staff = make_user(role=STAFF)

    created = client.post("/doctor-schedule/", headers=staff["headers"], json=SCHEDULE_PAYLOAD)
    assert created.status_code == 200, created.text
    doctor_id = created.json()["id"]

    updated = client.put(
        f"/doctor-schedule/{doctor_id}",
        headers=staff["headers"],
        json={"slot_duration": 15},
    )
    assert updated.status_code == 200
    assert updated.json()["slot_duration"] == 15

    deleted = client.delete(f"/doctor-schedule/{doctor_id}", headers=staff["headers"])
    assert deleted.status_code == 200


def test_staff_can_set_a_doctor_on_leave(client, make_user):
    """Time off is availability, so staff must be able to publish it."""
    staff = make_user(role=STAFF)
    created = client.post("/doctor-schedule/", headers=staff["headers"], json=SCHEDULE_PAYLOAD)
    doctor_id = created.json()["id"]

    response = client.put(
        f"/doctor-schedule/{doctor_id}",
        headers=staff["headers"],
        json={"leave_date": "2030-03-04"},
    )
    assert response.status_code == 200
    assert response.json()["leave_date"] == "2030-03-04"


def test_admin_can_also_manage_doctors(client, make_user):
    admin = make_user(role=ADMIN)
    response = client.post("/doctor-schedule/", headers=admin["headers"], json=SCHEDULE_PAYLOAD)
    assert response.status_code == 200, response.text
    client.delete(f"/doctor-schedule/{response.json()['id']}", headers=admin["headers"])


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_staff_cannot_manage_accounts(client, make_user, method, path):
    staff = make_user(role=STAFF)
    response = client.request(method, path, headers=staff["headers"], json={})
    assert response.status_code == 403, f"{method} {path} returned {response.status_code}"
    assert response.json()["detail"] == "Admin access required"


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_patients_cannot_manage_accounts(client, make_user, method, path):
    patient = make_user(role=PATIENT)
    response = client.request(method, path, headers=patient["headers"], json={})
    assert response.status_code == 403


def test_registration_always_creates_a_patient(client, make_user):
    """A role in the registration payload is ignored — patients cannot self-promote."""
    user = make_user(role=PATIENT)
    assert user["user"]["role"] == PATIENT

    response = client.post(
        "/api/auth/register",
        json={
            "first_name": "Sneaky",
            "last_name": "Patient",
            "email": "sneaky@example.com",
            "password": "Sup3rSecret1",
            "role": ADMIN,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["user"]["role"] == PATIENT


def test_admin_creates_a_staff_account_that_can_sign_in(client, make_user):
    admin = make_user(role=ADMIN)
    email = "nurse@example.com"

    created = client.post(
        "/api/auth/users",
        headers=admin["headers"],
        json={
            "first_name": "Nurse",
            "last_name": "Joy",
            "email": email,
            "password": "Sup3rSecret1",
            "role": STAFF,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == STAFF

    login = client.post("/api/auth/login", json={"email": email, "password": "Sup3rSecret1"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # The new staff account can do clinic work straight away...
    assert client.post("/doctor-schedule/", headers=headers, json=SCHEDULE_PAYLOAD).status_code == 200
    # ...but still cannot manage accounts.
    assert client.get("/api/auth/users", headers=headers).status_code == 403


def test_admin_can_create_another_admin(client, make_user):
    """Administrators can onboard each other; patients cannot reach this endpoint."""
    admin = make_user(role=ADMIN)
    response = client.post(
        "/api/auth/users",
        headers=admin["headers"],
        json={
            "first_name": "Second",
            "last_name": "Admin",
            "email": "second-admin@example.com",
            "password": "Sup3rSecret1",
            "role": ADMIN,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == ADMIN


def test_managed_user_cannot_be_created_as_a_patient_role(client, make_user):
    """Patients self-register; the admin endpoint only creates clinic accounts."""
    admin = make_user(role=ADMIN)
    response = client.post(
        "/api/auth/users",
        headers=admin["headers"],
        json={
            "first_name": "Odd",
            "last_name": "Role",
            "email": "odd-role@example.com",
            "password": "Sup3rSecret1",
            "role": PATIENT,
        },
    )
    assert response.status_code == 422


def test_invalid_role_is_rejected(client, make_user):
    admin = make_user(role=ADMIN)
    target = make_user(role=PATIENT)
    response = client.patch(
        f"/api/auth/users/{target['user']['id']}/role",
        headers=admin["headers"],
        json={"role": "superuser"},
    )
    assert response.status_code == 422


def test_admin_can_promote_a_patient_to_staff_and_the_change_is_immediate(client, make_user):
    admin = make_user(role=ADMIN)
    target = make_user(role=PATIENT)

    # A patient is refused before the change...
    refused = client.post("/doctor-schedule/", headers=target["headers"], json=SCHEDULE_PAYLOAD)
    assert refused.status_code == 403

    promoted = client.patch(
        f"/api/auth/users/{target['user']['id']}/role",
        headers=admin["headers"],
        json={"role": STAFF},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == STAFF

    # ...allowed immediately afterwards, even though the access token still
    # carries the old role claim: authorization reads the database, not the JWT.
    allowed = client.post("/doctor-schedule/", headers=target["headers"], json=SCHEDULE_PAYLOAD)
    assert allowed.status_code == 200, allowed.text
    client.delete(f"/doctor-schedule/{allowed.json()['id']}", headers=admin["headers"])


def test_role_change_revokes_the_targets_refresh_tokens(client, make_user):
    admin = make_user(role=ADMIN)
    target = make_user(role=PATIENT)

    before = client.post("/api/auth/refresh", json={"refresh_token": target["refresh_token"]})
    assert before.status_code == 200

    client.patch(
        f"/api/auth/users/{target['user']['id']}/role",
        headers=admin["headers"],
        json={"role": STAFF},
    )

    after = client.post("/api/auth/refresh", json={"refresh_token": target["refresh_token"]})
    assert after.status_code == 401


def test_admin_can_list_and_filter_users(client, make_user):
    admin = make_user(role=ADMIN)
    make_user(role=STAFF)

    everyone = client.get("/api/auth/users", headers=admin["headers"])
    assert everyone.status_code == 200
    assert len(everyone.json()) >= 3

    staff_only = client.get("/api/auth/users?role=staff", headers=admin["headers"])
    assert staff_only.status_code == 200
    assert {row["role"] for row in staff_only.json()} == {STAFF}


def test_last_active_admin_cannot_be_demoted(client, make_user):
    """The clinic must never be left without an administrator."""
    admin = make_user(role=ADMIN)

    # Park every *other* admin as staff so the caller is the only one left — the
    # test database is shared across the session, so other tests leave admins behind.
    with SessionLocal() as db:
        for user in repositories.get_all_users(db, role=ADMIN):
            if user.id != admin["user"]["id"]:
                repositories.set_user_role(db, user, STAFF)
        assert repositories.count_active_admins(db) == 1

    # Demoting the only remaining admin is refused...
    response = client.patch(
        f"/api/auth/users/{admin['user']['id']}/role",
        headers=admin["headers"],
        json={"role": PATIENT},
    )
    assert response.status_code == 400
    assert "administrator" in response.json()["detail"].lower()

    # ...but demoting an admin is fine while another one remains.
    second = make_user(role=ADMIN)
    allowed = client.patch(
        f"/api/auth/users/{second['user']['id']}/role",
        headers=admin["headers"],
        json={"role": STAFF},
    )
    assert allowed.status_code == 200


def test_admin_cannot_deactivate_their_own_account(client, make_user):
    admin = make_user(role=ADMIN)
    response = client.patch(
        f"/api/auth/users/{admin['user']['id']}/active",
        headers=admin["headers"],
        json={"is_active": False},
    )
    assert response.status_code == 400


def test_deactivating_an_account_blocks_sign_in_and_sessions(client, make_user):
    admin = make_user(role=ADMIN)
    target = make_user(role=STAFF)

    assert (
        client.patch(
            f"/api/auth/users/{target['user']['id']}/active",
            headers=admin["headers"],
            json={"is_active": False},
        ).status_code
        == 200
    )

    # The existing access token is refused, the session cannot be refreshed, and
    # a fresh sign-in is rejected with the same message as a wrong password.
    assert client.get("/api/auth/me", headers=target["headers"]).status_code == 401
    assert (
        client.post("/api/auth/refresh", json={"refresh_token": target["refresh_token"]}).status_code
        == 401
    )
    login = client.post(
        "/api/auth/login",
        json={"email": target["email"], "password": target["password"]},
    )
    assert login.status_code == 401
    assert login.json()["detail"] == "Invalid email or password"


def test_reactivated_account_can_sign_in_again(client, make_user):
    admin = make_user(role=ADMIN)
    target = make_user(role=STAFF)
    user_id = target["user"]["id"]

    for is_active in (False, True):
        response = client.patch(
            f"/api/auth/users/{user_id}/active",
            headers=admin["headers"],
            json={"is_active": is_active},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is is_active

    login = client.post(
        "/api/auth/login",
        json={"email": target["email"], "password": target["password"]},
    )
    assert login.status_code == 200


def test_unknown_account_is_not_found(client, make_user):
    admin = make_user(role=ADMIN)
    assert (
        client.patch(
            "/api/auth/users/999999/role",
            headers=admin["headers"],
            json={"role": STAFF},
        ).status_code
        == 404
    )


def test_bootstrap_admin_noops_when_env_is_unset(monkeypatch):
    for key in (
        "BOOTSTRAP_ADMIN_EMAIL",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "BOOTSTRAP_ADMIN_NAME",
        "BOOTSTRAP_ADMIN_PHONE",
    ):
        monkeypatch.delenv(key, raising=False)

    assert bootstrap_admin() == 0


def test_bootstrap_admin_creates_first_admin_from_env(monkeypatch):
    email = "bootstrap-admin@example.com"
    password = "Sup3rBootstrap1"

    with SessionLocal() as db:
        for user in repositories.get_all_users(db, role=ADMIN):
            repositories.set_user_role(db, user, STAFF)
        existing = repositories.get_user_by_email(db, email)
        if existing is not None:
            repositories.set_user_role(db, existing, STAFF)
        assert repositories.get_all_users(db, role=ADMIN) == []

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", email)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", password)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_NAME", "Bootstrap Admin")

    assert bootstrap_admin() == 0

    with SessionLocal() as db:
        user = repositories.get_user_by_email(db, email)
        assert user is not None
        assert user.role == ADMIN
        assert user.id and len(user.id) == 36

        audit = (
            db.query(AuditLog)
            .filter(AuditLog.action == "user.bootstrap_admin", AuditLog.entity_id == user.id)
            .first()
        )
        assert audit is not None
        assert audit.actor_email == "bootstrap"


def test_bootstrap_admin_is_idempotent_when_admin_exists(monkeypatch):
    first_email = "first-admin@example.com"
    second_email = "second-bootstrap-admin@example.com"

    with SessionLocal() as db:
        if repositories.get_user_by_email(db, first_email) is None:
            from app.schemas.user_auth import UserRegister
            from app.services.auth import hash_password

            repositories.create_user_account(
                db,
                UserRegister(email=first_email, password="Sup3rAdmin123"),
                hash_password("Sup3rAdmin123"),
                role=ADMIN,
            )

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", second_email)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "Sup3rBootstrap1")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_NAME", "Second Bootstrap")

    assert bootstrap_admin() == 0

    with SessionLocal() as db:
        assert repositories.get_user_by_email(db, second_email) is None
        assert repositories.get_all_users(db, role=ADMIN)


def test_bootstrap_admin_rejects_invalid_env(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "not-an-email")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "weak")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_NAME", "Bootstrap Admin")

    assert bootstrap_admin() == 1


def test_admin_can_hard_delete_team_account(client, make_user):
    admin = make_user(role=ADMIN)
    target = make_user(role=STAFF)

    response = client.delete(f"/api/auth/users/{target['user']['id']}", headers=admin["headers"])

    assert response.status_code == 200, response.text
    assert response.json()["message"] == "Account deleted"
    assert client.get("/api/auth/me", headers=target["headers"]).status_code == 401

    with SessionLocal() as db:
        assert repositories.get_user_by_email(db, target["email"]) is None


def test_admin_cannot_delete_self(client, make_user):
    admin = make_user(role=ADMIN)
    response = client.delete(f"/api/auth/users/{admin['user']['id']}", headers=admin["headers"])
    assert response.status_code == 400


def test_last_active_admin_cannot_be_deleted(client, make_user):
    admin = make_user(role=ADMIN)

    with SessionLocal() as db:
        for user in repositories.get_all_users(db, role=ADMIN):
            if user.id != admin["user"]["id"]:
                repositories.set_user_role(db, user, STAFF)
        assert repositories.count_active_admins(db) == 1

    other_admin = make_user(role=ADMIN)
    deleted = client.delete(f"/api/auth/users/{other_admin['user']['id']}", headers=admin["headers"])
    assert deleted.status_code == 200

    response = client.delete(f"/api/auth/users/{admin['user']['id']}", headers=admin["headers"])
    assert response.status_code == 400


def test_staff_can_add_doctor_photo(client, make_user):
    staff = make_user(role=STAFF)
    payload = {**SCHEDULE_PAYLOAD, "photo_url": "data:image/png;base64,iVBORw0KGgo="}

    response = client.post("/doctor-schedule/", headers=staff["headers"], json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["photo_url"] == payload["photo_url"]


def test_doctor_photo_rejects_unsafe_url(client, make_user):
    staff = make_user(role=STAFF)
    payload = {**SCHEDULE_PAYLOAD, "photo_url": "javascript:alert(1)"}

    response = client.post("/doctor-schedule/", headers=staff["headers"], json=payload)

    assert response.status_code == 422
