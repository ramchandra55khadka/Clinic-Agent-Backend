"""Authorization matrix: what anonymous, patient and admin callers may reach."""

import pytest

ANONYMOUS_ALLOWED = ["/health", "/health/live", "/"]

PROTECTED_ENDPOINTS = [
    ("GET", "/doctor-schedule/"),
    ("GET", "/doctor-schedule/1"),
    ("POST", "/availability/"),
    ("GET", "/availability/1/2030-01-01"),
    ("GET", "/appointments/1"),
    ("POST", "/appointments/"),
    ("POST", "/chat"),
    ("POST", "/rag"),
    ("POST", "/mcp/check-availability"),
    ("POST", "/mcp/book-appointment"),
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/change-password"),
]

ADMIN_ONLY_MUTATIONS = [
    ("POST", "/doctor-schedule/"),
    ("PUT", "/doctor-schedule/1"),
    ("DELETE", "/doctor-schedule/1"),
    ("GET", "/appointments/1"),
]


@pytest.mark.parametrize("path", ANONYMOUS_ALLOWED)
def test_public_endpoints_are_open(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_protected_endpoints_reject_anonymous_callers(client, method, path):
    response = client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} returned {response.status_code}"
    assert "WWW-Authenticate" in response.headers


@pytest.mark.parametrize("method,path", ADMIN_ONLY_MUTATIONS)
def test_patients_cannot_reach_admin_endpoints(client, make_user, method, path):
    patient = make_user(role="patient")
    response = client.request(method, path, headers=patient["headers"], json={})
    assert response.status_code == 403, f"{method} {path} returned {response.status_code}"


def test_admin_can_manage_schedules(client, make_user):
    admin = make_user(role="admin")

    created = client.post(
        "/doctor-schedule/",
        headers=admin["headers"],
        json={
            "doctor_name": "Dr. Admin Owned",
            "start_time": "08:00:00",
            "end_time": "12:00:00",
            "slot_duration": 15,
        },
    )
    assert created.status_code == 200, created.text
    doctor_id = created.json()["id"]

    updated = client.put(
        f"/doctor-schedule/{doctor_id}",
        headers=admin["headers"],
        json={"specialization": "Cardiology"},
    )
    assert updated.status_code == 200
    assert updated.json()["specialization"] == "Cardiology"

    deleted = client.delete(f"/doctor-schedule/{doctor_id}", headers=admin["headers"])
    assert deleted.status_code == 200


def test_patients_can_read_reference_data(client, make_user, doctor):
    patient = make_user(role="patient")

    assert client.get("/doctor-schedule/", headers=patient["headers"]).status_code == 200
    assert (
        client.get(f"/doctor-schedule/{doctor['schedule']['id']}", headers=patient["headers"]).status_code == 200
    )
    available = client.post(
        "/availability/",
        headers=patient["headers"],
        json={"doctor_id": doctor["schedule"]["id"], "date": "2030-01-07"},
    )
    assert available.status_code == 200


def test_mcp_tools_require_authentication(client, make_user, doctor):
    payload = {"doctor_id": doctor["schedule"]["id"], "date": "2030-01-07"}

    assert client.post("/mcp/check-availability", json=payload).status_code == 401

    patient = make_user(role="patient")
    response = client.post("/mcp/check-availability", headers=patient["headers"], json=payload)
    assert response.status_code == 200
    assert "slots" in response.json()
