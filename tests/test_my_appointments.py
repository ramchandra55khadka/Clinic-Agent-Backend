"""Self-service appointment listing and detail (ownership isolation)."""

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


def test_patient_lists_only_their_own_appointments(client, make_user, doctor):
    doctor_id = doctor["schedule"]["id"]
    patient = make_user()
    other = make_user()

    mine = _book(client, patient["headers"], _appointment_payload(doctor_id, patient["email"]))
    _book(client, other["headers"], _appointment_payload(doctor_id, other["email"], time="10:00:00"))

    response = client.get("/appointments/me", headers=patient["headers"])
    assert response.status_code == 200, response.text

    rows = response.json()
    assert [row["id"] for row in rows] == [mine["id"]]
    assert rows[0]["email"] == patient["email"]


def test_my_appointments_requires_authentication(client):
    assert client.get("/appointments/me").status_code == 401


def test_detail_returns_the_appointment_for_its_owner(client, make_user, doctor):
    patient = make_user()
    booked = _book(
        client, patient["headers"], _appointment_payload(doctor["schedule"]["id"], patient["email"])
    )

    response = client.get(f"/appointments/me/{booked['id']}", headers=patient["headers"])
    assert response.status_code == 200
    assert response.json()["id"] == booked["id"]


def test_detail_of_someone_elses_appointment_is_not_found(client, make_user, doctor):
    """404 rather than 403: another patient's booking must not even be confirmed."""
    owner = make_user()
    intruder = make_user()
    booked = _book(
        client, owner["headers"], _appointment_payload(doctor["schedule"]["id"], owner["email"])
    )

    response = client.get(f"/appointments/me/{booked['id']}", headers=intruder["headers"])
    assert response.status_code == 404


def test_unknown_appointment_id_is_not_found(client, make_user):
    patient = make_user()
    assert client.get("/appointments/me/999999", headers=patient["headers"]).status_code == 404


def test_availability_exclusion_ignores_appointments_you_do_not_own(client, make_user, doctor):
    """The reschedule picker must not let a patient erase someone else's booking."""
    owner = make_user()
    intruder = make_user()
    doctor_id = doctor["schedule"]["id"]
    booked = _book(client, owner["headers"], _appointment_payload(doctor_id, owner["email"]))

    response = client.get(
        f"/availability/{doctor_id}/{FUTURE_DATE}?exclude_appointment_id={booked['id']}",
        headers=intruder["headers"],
    )
    assert response.status_code == 200
    slot = next(s for s in response.json()["slots"] if s["time"] == "09:00:00")
    assert slot["available"] is False


def test_availability_exclusion_applies_for_the_owner(client, make_user, doctor):
    patient = make_user()
    doctor_id = doctor["schedule"]["id"]
    booked = _book(client, patient["headers"], _appointment_payload(doctor_id, patient["email"]))

    response = client.get(
        f"/availability/{doctor_id}/{FUTURE_DATE}?exclude_appointment_id={booked['id']}",
        headers=patient["headers"],
    )
    slot = next(s for s in response.json()["slots"] if s["time"] == "09:00:00")
    assert slot["available"] is True