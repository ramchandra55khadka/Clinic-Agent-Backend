"""The one-way links between ``user_profile`` and the doctor/patient rows.

``UserProfile`` deliberately exposes **no** reverse ``doctor``/``patient``
relationships (see ``app.models.user_profile``): doctor and patient own the FK
(``profile_id``), so the profile is never walked backwards into a role row.
These tests pin the explicit ``profile_id`` lookups and the relocated
delete-cascade that replaced those back-references.
"""

from app import repositories
from app.db.session import SessionLocal
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.models.user_profile import UserProfile


def test_user_profile_exposes_no_reverse_role_relationships():
    """Doctor/patient own the FK; the profile must not back-reference them."""
    assert not hasattr(UserProfile, "doctor")
    assert not hasattr(UserProfile, "patient")


def test_ensure_patient_for_user_reuses_the_onboarding_patient_row(make_user):
    """The ``patient`` row added when the profile is created is reused, not duplicated."""
    account = make_user(role="patient")

    with SessionLocal() as db:
        user = repositories.get_user_by_email(db, account["email"])
        profile = repositories.get_profile_by_user_id(db, user.id)
        first = repositories.ensure_patient_for_user(db, user)
        second = repositories.ensure_patient_for_user(db, user)
        rows = db.query(Patient).filter(Patient.profile_id == profile.id).all()

    assert first.id == second.id
    assert [row.id for row in rows] == [first.id]


def test_deleting_a_doctor_schedule_removes_the_doctor_and_its_profile(client, make_user):
    """The cascade now runs doctor -> schedule and profile -> gone, in one call."""
    admin = make_user(role="admin")
    created = client.post(
        "/doctor-schedule/",
        headers=admin["headers"],
        json={
            "first_name": "Cascade",
            "last_name": "Check",
            "specialization": "Dermatology",
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "slot_duration": 30,
        },
    )
    assert created.status_code == 200, created.text
    doctor_id = created.json()["id"]

    with SessionLocal() as db:
        profile_id = db.query(Doctor).filter(Doctor.id == doctor_id).one().profile_id

    deleted = client.delete(f"/doctor-schedule/{doctor_id}", headers=admin["headers"])
    assert deleted.status_code == 200, deleted.text

    with SessionLocal() as db:
        assert db.get(Doctor, doctor_id) is None
        assert db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == doctor_id).first() is None
        assert db.get(UserProfile, profile_id) is None
