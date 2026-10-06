"""Working days on doctor schedules: storage, validation and availability."""

from datetime import date, timedelta


def _date_named(name: str) -> date:
    """A future date (at least a week out) whose weekday name matches `name`."""
    for offset in range(7, 14):
        candidate = date.today() + timedelta(days=offset)
        if candidate.strftime("%A") == name:
            return candidate
    raise AssertionError(f"no {name} in the next two weeks")


def _appointment_payload(doctor_id: int, when: date, **overrides) -> dict:
    payload = {
        "doctor_id": doctor_id,
        "patient_name": "Rahul Sharma",
        "age": 34,
        "sex": "male",
        "email": "rahul@example.com",
        "phone": "9876543210",
        "date": when.isoformat(),
        "time": "10:00:00",
    }
    payload.update(overrides)
    return payload


def test_days_are_stored_and_returned_in_canonical_order(client, make_user):
    admin = make_user(role="admin")
    response = client.post(
        "/doctor-schedule/",
        headers=admin["headers"],
        json={
            "first_name": "Anjali",
            "last_name": "Sharma",
            "specialization": "Dermatology",
            "start_time": "10:00:00",
            "end_time": "16:00:00",
            "slot_duration": 30,
            "days": ["Monday", "Sunday"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == ["Sunday", "Monday"]

    listing = client.get("/doctor-schedule/", headers=admin["headers"])
    assert listing.status_code == 200
    saved = next(row for row in listing.json() if row["schedule_id"] == body["schedule_id"])
    assert saved["days"] == ["Sunday", "Monday"]


def test_schedule_without_days_reports_every_day(client, make_user):
    admin = make_user(role="admin")
    response = client.post(
        "/doctor-schedule/",
        headers=admin["headers"],
        json={
            "first_name": "Prakash",
            "last_name": "Thapa",
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "slot_duration": 30,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["days"] == [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]


def test_unknown_or_empty_day_lists_are_rejected(client, make_user):
    admin = make_user(role="admin")
    base = {
        "first_name": "Sita",
        "start_time": "09:00:00",
        "end_time": "17:00:00",
        "slot_duration": 30,
    }

    unknown = client.post("/doctor-schedule/", headers=admin["headers"], json={**base, "days": ["Funday"]})
    assert unknown.status_code == 422, unknown.text

    empty = client.post("/doctor-schedule/", headers=admin["headers"], json={**base, "days": []})
    assert empty.status_code == 422, empty.text


def test_off_day_has_no_open_slots_and_blocks_booking(client, make_user, doctor):
    admin = doctor["admin"]
    doctor_id = doctor["schedule"]["id"]
    working_day = _date_named("Monday")
    off_day = _date_named("Tuesday")

    updated = client.put(
        f"/doctor-schedule/{doctor_id}",
        headers=admin["headers"],
        json={"days": ["Monday"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["days"] == ["Monday"]

    # Slots are still listed on the off day, but every one of them is rejected
    # with a machine-readable reason (mirrors how leave dates behave).
    off_slots = client.get(f"/availability/{doctor_id}/{off_day}", headers=admin["headers"]).json()["slots"]
    assert off_slots
    assert all(slot["reason"] == "not_working_day" for slot in off_slots)
    assert not any(slot["available"] for slot in off_slots)

    working_slots = client.get(f"/availability/{doctor_id}/{working_day}", headers=admin["headers"]).json()["slots"]
    assert any(slot["available"] for slot in working_slots)

    patient = make_user()
    blocked = client.post(
        "/appointments/",
        headers=patient["headers"],
        json=_appointment_payload(doctor_id, off_day),
    )
    assert blocked.status_code == 400, blocked.text
    assert "not working day" in blocked.json()["detail"]

    booked = client.post(
        "/appointments/",
        headers=patient["headers"],
        json=_appointment_payload(doctor_id, working_day),
    )
    assert booked.status_code == 200, booked.text


def test_legacy_schedule_without_days_is_bookable_any_day(client, doctor):
    """Rows written before working days existed keep their every-day meaning."""
    doctor_id = doctor["schedule"]["id"]
    admin = doctor["admin"]
    any_day = _date_named("Saturday")

    response = client.get(f"/availability/{doctor_id}/{any_day}", headers=admin["headers"])
    assert response.status_code == 200
    assert any(slot["available"] for slot in response.json()["slots"])
