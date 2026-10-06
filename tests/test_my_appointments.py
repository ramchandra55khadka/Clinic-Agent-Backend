"""Self-service appointment listing and detail (ownership isolation)."""

from app import repositories
from app.db.session import SessionLocal

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


def test_chat_answers_my_appointment_history_from_database(client, make_user, doctor):
    doctor_id = doctor["schedule"]["id"]
    patient = make_user()
    other = make_user()

    mine = _book(client, patient["headers"], _appointment_payload(doctor_id, patient["email"]))
    _book(client, other["headers"], _appointment_payload(doctor_id, other["email"], time="10:00:00"))

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "show my appointment history records"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "booking"
    assert body["data"]["source"] == "database"
    assert body["data"]["count"] == 1
    assert body["data"]["appointments"][0]["id"] == mine["id"]
    assert patient["email"] in body["response"]
    assert other["email"] not in body["response"]


def test_chat_my_appointment_history_empty(client, make_user):
    patient = make_user()

    response = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "what are my upcoming appointments"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == {"source": "database", "appointments": [], "count": 0}
    assert "could not find any appointments" in body["response"].lower()


def test_chat_booking_is_tracked_by_the_account_not_the_typed_email(client, make_user, doctor):
    """A booking made in chat belongs to the session's account even when the
    patient types a different email during the conversation."""
    patient = make_user()
    session_id = None

    steps = [
        (
            {
                "message": "I want to book appointment at 9:00 AM.",
                "doctor_id": doctor["schedule"]["id"],
                "appointment_date": FUTURE_DATE,
                "appointment_time": "09:00:00",
            },
            "patient_name",
        ),
        ({"message": "Walk-in Guest"}, "age"),
        ({"message": "41"}, "sex"),
        ({"message": "Female"}, "email"),
        ({"message": "typed-during-chat@example.com"}, "phone"),
        ({"message": "9876543210"}, "confirmation"),
    ]

    for payload, required in steps:
        if session_id:
            payload["session_id"] = session_id
        response = client.post("/chat", headers=patient["headers"], json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        session_id = body["session_id"]
        assert body["data"]["required"] == [required]

    confirmed = client.post(
        "/chat",
        headers=patient["headers"],
        json={"session_id": session_id, "message": "yes"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["data"]["status"] == "success"
    appointment_id = body["data"]["appointment"]["id"]

    # The account tracks it although the typed email is a different address.
    mine = client.get("/appointments/me", headers=patient["headers"])
    assert mine.status_code == 200, mine.text
    rows = {row["id"]: row for row in mine.json()}
    assert appointment_id in rows
    assert rows[appointment_id]["email"] == "typed-during-chat@example.com"

    history = client.post(
        "/chat",
        headers=patient["headers"],
        json={"message": "show my appointment history records"},
    )
    assert history.status_code == 200, history.text
    tracked = {row["id"] for row in history.json()["data"]["appointments"]}
    assert appointment_id in tracked

    detail = client.get(f"/appointments/me/{appointment_id}", headers=patient["headers"])
    assert detail.status_code == 200, detail.text


def test_patient_link_grants_ownership_without_matching_email(client, make_user, doctor):
    """The patient row is the ownership anchor: list, detail and the reschedule
    picker all resolve through it even when the booking email differs."""
    owner = make_user()
    intruder = make_user()
    doctor_id = doctor["schedule"]["id"]

    booked = _book(
        client, owner["headers"], _appointment_payload(doctor_id, "someone-else@example.com")
    )

    # The link the chat route writes at booking time.
    with SessionLocal() as db:
        user = repositories.get_user_by_email(db, owner["email"])
        patient = repositories.ensure_patient_for_user(db, user)
        appointment = repositories.get_appointment(db, booked["id"])
        appointment.patient_id = patient.id
        db.commit()

    listed = client.get("/appointments/me", headers=owner["headers"])
    assert listed.status_code == 200, listed.text
    assert booked["id"] in {row["id"] for row in listed.json()}

    assert (
        client.get(f"/appointments/me/{booked['id']}", headers=owner["headers"]).status_code
        == 200
    )
    assert (
        client.get(f"/appointments/me/{booked['id']}", headers=intruder["headers"]).status_code
        == 404
    )

    # The reschedule picker honours the link: the owner sees their slot as free.
    excluded = client.get(
        f"/availability/{doctor_id}/{FUTURE_DATE}?exclude_appointment_id={booked['id']}",
        headers=owner["headers"],
    )
    assert excluded.status_code == 200
    slot = next(s for s in excluded.json()["slots"] if s["time"] == "09:00:00")
    assert slot["available"] is True

    ignored = client.get(
        f"/availability/{doctor_id}/{FUTURE_DATE}?exclude_appointment_id={booked['id']}",
        headers=intruder["headers"],
    )
    assert ignored.status_code == 200
    slot = next(s for s in ignored.json()["slots"] if s["time"] == "09:00:00")
    assert slot["available"] is False


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
