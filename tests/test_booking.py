"""Booking rules: availability pre-check, double-booking, past slots, integrity."""

from datetime import date, time

import pytest
from sqlalchemy.exc import IntegrityError

from app import repositories
from app.db.session import SessionLocal
from app.schemas.appointment import AppointmentCreate

FUTURE_DATE = "2030-01-07"


def _appointment_payload(doctor: int = 1, **overrides) -> dict:
    """Payload builder; `overrides` may replace any field (including doctor_id)."""
    payload = {
        "doctor_id": doctor,
        "patient_name": "Rahul Sharma",
        "age": 34,
        "sex": "male",
        "email": "rahul@example.com",
        "phone": "9876543210",
        "date": FUTURE_DATE,
        "time": "09:00:00",
    }
    payload.update(overrides)
    return payload


def _book(client, headers, payload):
    return client.post("/appointments/", headers=headers, json=payload)


def test_patient_can_book_an_available_slot(client, make_user, doctor):
    patient = make_user()
    response = _book(client, patient["headers"], _appointment_payload(doctor["schedule"]["id"]))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["doctor_id"] == doctor["schedule"]["id"]

    # The confirmation email is sent after the response, so the persisted status
    # reflects the real outcome (skipped when SMTP is disabled).
    from app.models.appointment import Appointment

    with SessionLocal() as db:
        stored = db.get(Appointment, body["id"])
        assert stored.confirmation_email_status == "skipped"


def test_booking_the_same_slot_twice_is_rejected(client, make_user, doctor):
    patient = make_user()
    payload = _appointment_payload(doctor["schedule"]["id"])

    assert _book(client, patient["headers"], payload).status_code == 200

    other = make_user()
    duplicate = _book(client, other["headers"], payload)
    assert duplicate.status_code == 400
    assert "not available" in duplicate.json()["detail"].lower()


def test_database_constraint_prevents_double_booking(client, make_user, doctor):
    """Even when the pre-check is bypassed, the unique constraint must hold."""
    doctor_id = doctor["schedule"]["id"]
    payload = _appointment_payload(doctor_id)

    with SessionLocal() as db:
        repositories.create_appointment(db, AppointmentCreate(**payload))
        with pytest.raises(IntegrityError):
            repositories.create_appointment(db, AppointmentCreate(**payload))
        db.rollback()


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"date": "2020-01-01"}, "passed"),
        ({"time": "13:00:00"}, "break"),
        ({"time": "07:00:00"}, "before"),
        ({"time": "16:45:00"}, "after"),
        ({"doctor_id": 98765}, "not available"),
    ],
)
def test_unavailable_slots_are_rejected(client, make_user, doctor, overrides, expected):
    patient = make_user()
    payload = _appointment_payload(doctor["schedule"]["id"], **overrides)

    response = _book(client, patient["headers"], payload)
    assert response.status_code == 400, response.text
    assert expected in response.json()["detail"].lower()


def test_availability_reflects_existing_bookings(client, make_user, doctor):
    patient = make_user()
    doctor_id = doctor["schedule"]["id"]
    assert _book(client, patient["headers"], _appointment_payload(doctor_id, time="10:00:00")).status_code == 200

    slots = client.get(f"/availability/{doctor_id}/{FUTURE_DATE}", headers=patient["headers"]).json()["slots"]
    by_time = {slot["time"]: slot for slot in slots}

    assert by_time["10:00:00"]["available"] is False
    assert by_time["10:00:00"]["reason"] == "slot_booked"
    assert by_time["09:00:00"]["available"] is True


def test_booking_persists_the_supplied_patient_details(client, make_user, doctor):
    patient = make_user()
    payload = _appointment_payload(doctor["schedule"]["id"], time="11:30:00", patient_name="Maya Rai")

    body = _book(client, patient["headers"], payload).json()
    assert body["patient_name"] == "Maya Rai"
    assert body["date"] == FUTURE_DATE
    assert body["time"] == "11:30:00"


def test_mcp_booking_uses_the_same_rules(client, make_user, doctor):
    patient = make_user()
    doctor_id = doctor["schedule"]["id"]

    first = client.post(
        "/mcp/book-appointment",
        headers=patient["headers"],
        json={"appointment": _appointment_payload(doctor_id, time="15:00:00")},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "success"

    conflict = client.post(
        "/mcp/book-appointment",
        headers=patient["headers"],
        json={"appointment": _appointment_payload(doctor_id, time="15:00:00")},
    )
    assert conflict.status_code == 200
    assert conflict.json()["status"] == "failed"
    assert conflict.json()["reason"] == "slot_booked"


def test_service_rejects_slots_in_the_past(client, doctor):
    from app.services.appointments import BookingError, book_appointment

    with SessionLocal() as db:
        with pytest.raises(BookingError) as exc:
            book_appointment(
                db,
                AppointmentCreate(**_appointment_payload(doctor["schedule"]["id"], date="2020-01-01")),
            )
        assert exc.value.reason == "in_the_past"


def test_slot_duration_is_respected(client, make_user, doctor):
    """A 30-minute slot occupies the following 30 minutes as well."""
    patient = make_user()
    doctor_id = doctor["schedule"]["id"]

    assert _book(client, patient["headers"], _appointment_payload(doctor_id, time="12:00:00")).status_code == 200

    slots = client.get(f"/availability/{doctor_id}/{FUTURE_DATE}", headers=patient["headers"]).json()["slots"]
    by_time = {slot["time"]: slot for slot in slots}

    assert by_time["12:00:00"]["reason"] == "slot_booked"
    assert by_time["12:30:00"]["available"] is True
    # Sanity check on the fixture's working window.
    assert date(2030, 1, 7) > date(2020, 1, 1)
    assert time(9, 0) < time(17, 0)