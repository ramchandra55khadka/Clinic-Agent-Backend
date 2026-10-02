"""Test configuration.

Environment variables are set *before* the application is imported, because
``app.core.config`` reads them at import time. Tests run against a throwaway SQLite
file and never touch the Postgres database configured in ``.env``.
"""

import os
from pathlib import Path
from uuid import uuid4

TEST_DATABASE = Path(__file__).resolve().parent / "test_clinic.db"

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE}"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-0123456789abcdefghij"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["CREATE_TABLES_ON_STARTUP"] = "true"
os.environ["EMAIL_ENABLED"] = "false"
os.environ["ENABLE_DOCS"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["LOG_JSON"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401  (registers every model on Base.metadata)
from app import repositories  # noqa: E402
from app.core.rate_limit import store  # noqa: E402
from app.db.session import Base, SessionLocal, engine  # noqa: E402

DEFAULT_PASSWORD = "Sup3rSecret1"


@pytest.fixture(scope="session", autouse=True)
def _fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    TEST_DATABASE.unlink(missing_ok=True)


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    store.reset()


@pytest.fixture()
def make_user(client):
    """Registers a fresh account through the API (optionally promoting a role).

    Returns a dict with the email, password, bearer headers, refresh token and
    profile — the shape the other tests need to call protected endpoints.
    """

    def _make(role: str = "patient", password: str = DEFAULT_PASSWORD) -> dict:
        email = f"{role}-{uuid4().hex[:10]}@example.com"
        response = client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        headers = {"Authorization": f"Bearer {body['access_token']}"}

        if role != "patient":
            with SessionLocal() as db:
                user = repositories.get_user_by_email(db, email)
                repositories.set_user_role(db, user, role)

        # Personal details are a separate call: the profile is decoupled from the
        # account (creating it also gives a patient account its ``patient`` row).
        profile = client.post(
            "/api/profiles",
            headers=headers,
            json={"first_name": "Test", "last_name": "User"},
        )
        assert profile.status_code == 201, profile.text

        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200, me.text

        return {
            "email": email,
            "password": password,
            "headers": headers,
            "refresh_token": body["refresh_token"],
            "user": me.json(),
        }

    return _make


@pytest.fixture()
def doctor(client, make_user):
    """An admin-created doctor schedule, plus the admin credentials used to make it."""
    admin = make_user(role="admin")
    response = client.post(
        "/doctor-schedule/",
        headers=admin["headers"],
        json={
            "doctor_name": "Dr. Test Sharma",
            "specialization": "General Medicine",
            "start_time": "09:00:00",
            "end_time": "17:00:00",
            "break_start": "13:00:00",
            "break_end": "14:00:00",
            "slot_duration": 30,
        },
    )
    assert response.status_code == 200, response.text
    return {"admin": admin, "schedule": response.json()}