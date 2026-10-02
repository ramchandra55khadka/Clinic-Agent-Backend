"""Self-service cancellation and ownership enforcement."""

from app.db.session import SessionLocal
from app.models.audit_log import AuditLog

FUTURE_DATE = "2030-01-07"


def _appointment_payload(doctor_id: int, email: str, **overrides) -> dict:
    payload = {
        "doctor_id": doctor_id,
        "patient_name": "Sita Sharma",
        "age": 34,
        "sex": "female",
        "email": email,
        "phone": "9876543210",
        "date": FUTURE_DATE,
        "time": "09:00:00",
    }
    payload.update(overrides)
    return payload


def _book(client, headers, payload):
    response = client.post("/appointments/", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_patient_can_cancel_and_the_slot_frees_up(client, make_user, doctor):
    patient = make_user()
    doctor_id = doctor["schedule"]["id"]
    booked = _book(client, patient["headers"], _appointment_payload(doctor_id, patient["email"]))

    response = client.post(f"/appointments/me/{booked['id']}/cancel", headers=patient["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    slots = client.get(f"/availability/{doctor_id}/{FUTURE_DATE}", headers=patient["headers"]).json()["slots"]
    assert next(s for s in slots if s["time"] == "09:00:00")["available"] is True


def test_cancelled_appointment_cannot_be_edited(client, make_user, doctor):
    patient = make_user()
    booked = _book(
        client, patient["headers"], _appointment_payload(doctor["schedule"]["id"], patient["email"])
    )
    client.post(f"/appointments/me/{booked['id']}/cancel", headers=patient["headers"])

    response = client.put(
        f"/appointments/me/{booked['id']}", headers=patient["headers"], json={"patient_name": "Too Late"}
    )
    assert response.status_code == 400


def test_cancelling_twice_is_idempotent(client, make_user, doctor):
    patient = make_user()
    booked = _book(
        client, patient["headers"], _appointment_payload(doctor["schedule"]["id"], patient["email"])
    )

    first = client.post(f"/appointments/me/{booked['id']}/cancel", headers=patient["headers"])
    second = client.post(f"/appointments/me/{booked['id']}/cancel", headers=patient["headers"])

    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "cancelled"


def test_another_patient_cannot_edit_or_cancel(client, make_user, doctor):
    owner = make_user()
    intruder = make_user()
    booked = _book(
        client, owner["headers"], _appointment_payload(doctor["schedule"]["id"], owner["email"])
    )

    edit = client.put(
        f"/appointments/me/{booked['id']}",
        headers=intruder["headers"],
        json={"patient_name": "Hijacked"},
    )
    cancel = client.post(f"/appointments/me/{booked['id']}/cancel", headers=intruder["headers"])

    assert edit.status_code == 404
    assert cancel.status_code == 404

    still_mine = client.get(f"/appointments/me/{booked['id']}", headers=owner["headers"]).json()
    assert still_mine["patient_name"] == "Sita Sharma"
    assert still_mine["status"] == "confirmed"


def test_self_service_changes_are_audited(client, make_user, doctor):
    patient = make_user()
    booked = _book(
        client, patient["headers"], _appointment_payload(doctor["schedule"]["id"], patient["email"])
    )

    client.put(f"/appointments/me/{booked['id']}", headers=patient["headers"], json={"age": 40})
    client.post(f"/appointments/me/{booked['id']}/cancel", headers=patient["headers"])

    with SessionLocal() as db:
        actions = {row.action for row in db.query(AuditLog).all()}

    assert {"appointment.updated", "appointment.cancelled"} <= actions