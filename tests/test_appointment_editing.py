"""Self-service editing: rescheduling and detail changes."""

from datetime import date, timedelta

FUTURE_DATE = "2030-01-07"
OTHER_DATE = "2030-01-08"


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


def test_patient_can_edit_their_details(client, make_user, doctor):
    patient = make_user()
    booked = _book(
        client, patient["headers"], _appointment_payload(doctor["schedule"]["id"], patient["email"])
    )

    response = client.put(
        f"/appointments/me/{booked['id']}",
        headers=patient["headers"],
        json={"patient_name": "Sita S. Sharma", "age": 35, "phone": "9812345678"},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["patient_name"] == "Sita S. Sharma"
    assert body["age"] == 35
    assert body["phone"] == "9812345678"
    # Unchanged fields survive.
    assert body["date"] == FUTURE_DATE
    assert body["time"] == "09:00:00"
    assert body["doctor_id"] == doctor["schedule"]["id"]


def test_patient_can_reschedule_to_a_free_slot(client, make_user, doctor):
    patient = make_user()
    doctor_id = doctor["schedule"]["id"]
    booked = _book(client, patient["headers"], _appointment_payload(doctor_id, patient["email"]))

    response = client.put(
        f"/appointments/me/{booked['id']}",
        headers=patient["headers"],
        json={"date": OTHER_DATE, "time": "11:00:00"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["date"] == OTHER_DATE
    assert response.json()["time"] == "11:00:00"

    old_day = client.get(f"/availability/{doctor_id}/{FUTURE_DATE}", headers=patient["headers"]).json()
    assert next(s for s in old_day["slots"] if s["time"] == "09:00:00")["available"] is True

    new_day = client.get(f"/availability/{doctor_id}/{OTHER_DATE}", headers=patient["headers"]).json()
    assert next(s for s in new_day["slots"] if s["time"] == "11:00:00")["available"] is False


def test_keeping_the_same_slot_is_allowed(client, make_user, doctor):
    """Rescheduling must not collide with the appointment being edited."""
    patient = make_user()
    booked = _book(
        client, patient["headers"], _appointment_payload(doctor["schedule"]["id"], patient["email"])
    )

    response = client.put(
        f"/appointments/me/{booked['id']}",
        headers=patient["headers"],
        json={"date": FUTURE_DATE, "time": "09:00:00", "patient_name": "Renamed Patient"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["time"] == "09:00:00"


def test_rescheduling_onto_a_taken_slot_is_rejected(client, make_user, doctor):
    doctor_id = doctor["schedule"]["id"]
    patient = make_user()
    other = make_user()

    _book(client, other["headers"], _appointment_payload(doctor_id, other["email"], time="11:00:00"))
    mine = _book(client, patient["headers"], _appointment_payload(doctor_id, patient["email"]))

    response = client.put(
        f"/appointments/me/{mine['id']}", headers=patient["headers"], json={"time": "11:00:00"}
    )
    assert response.status_code == 400
    assert "not available" in response.json()["detail"].lower()


def test_rescheduling_into_the_past_is_rejected(client, make_user, doctor):
    patient = make_user()
    booked = _book(
        client, patient["headers"], _appointment_payload(doctor["schedule"]["id"], patient["email"])
    )
    past = (date.today() - timedelta(days=1)).isoformat()

    response = client.put(
        f"/appointments/me/{booked['id']}", headers=patient["headers"], json={"date": past}
    )
    assert response.status_code == 400
    assert "passed" in response.json()["detail"].lower()