"""Registration, login, lockout and access-token validation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import settings

DEFAULT_PASSWORD = "Sup3rSecret1"


def _register(client, email="new-user@example.com", password=DEFAULT_PASSWORD):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )


def test_register_returns_tokens(client):
    response = _register(client)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["expires_in"] == settings.access_token_expire_minutes * 60
    assert body["user"]["email"] == "new-user@example.com"
    assert body["user"]["role"] == "patient"
    assert "password" not in body["user"]


def test_profile_is_created_separately_from_the_account(client):
    """Registration creates only the account; personal data is a second call."""
    body = _register(client, email="profile-split@example.com").json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    # No profile yet, so the flat user shape has no name.
    assert body["user"]["first_name"] == ""

    created = client.post(
        "/api/profiles",
        headers=headers,
        json={
            "first_name": "Asha",
            "last_name": "Rai",
            "phone": "9800000000",
            "date_of_birth": "1990-05-14",
            "gender": "Female",
            "address": "Kathmandu",
        },
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["first_name"] == "Asha"
    assert profile["last_name"] == "Rai"
    assert profile["phone"] == "9800000000"
    assert profile["date_of_birth"] == "1990-05-14"
    assert profile["gender"] == "Female"
    assert profile["address"] == "Kathmandu"
    # The email is copied from the account, never sent by the client.
    assert profile["email"] == "profile-split@example.com"

    me = client.get("/api/auth/me", headers=headers).json()
    assert me["first_name"] == "Asha"
    assert me["date_of_birth"] == "1990-05-14"

    # A profile can only be created once per account.
    assert client.post("/api/profiles", headers=headers, json={"first_name": "Again"}).status_code == 409


def test_register_rejects_duplicate_email(client):
    _register(client, email="duplicate@example.com")
    assert _register(client, email="duplicate@example.com").status_code == 409


@pytest.mark.parametrize("password", ["short1", "alllettersnodigit", "12345678901", "password"])
def test_register_enforces_password_policy(client, password):
    response = _register(client, email=f"weak-{password}@example.com", password=password)
    assert response.status_code == 422




def test_update_me_changes_profile_fields(client, make_user):
    user = make_user()
    photo = "data:image/png;base64,iVBORw0KGgo="

    response = client.patch(
        "/api/auth/me",
        headers=user["headers"],
        json={
            "first_name": "Updated",
            "last_name": "Patient",
            "phone": "9866835892",
            "photo_url": photo,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Updated"
    assert body["last_name"] == "Patient"
    assert body["phone"] == "9866835892"
    assert body["photo_url"] == photo
    assert body["email"] == user["email"]
    assert body["role"] == "patient"


def test_update_me_rejects_unsafe_profile_photo(client, make_user):
    user = make_user()
    response = client.patch(
        "/api/auth/me",
        headers=user["headers"],
        json={"photo_url": "javascript:alert(1)"},
    )
    assert response.status_code == 422


def test_login_succeeds(client, make_user):
    user = make_user()
    response = client.post(
        "/api/auth/login", json={"email": user["email"], "password": user["password"]}
    )
    assert response.status_code == 200
    assert response.json()["user"]["email"] == user["email"]


def test_login_failures_are_indistinguishable(client, make_user):
    user = make_user()

    wrong_password = client.post(
        "/api/auth/login", json={"email": user["email"], "password": "WrongPass123"}
    )
    unknown_user = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "WrongPass123"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_account_locks_after_repeated_failures(client, make_user):
    user = make_user()

    for _ in range(settings.max_failed_login_attempts):
        attempt = client.post(
            "/api/auth/login", json={"email": user["email"], "password": "WrongPass123"}
        )
        assert attempt.status_code == 401

    locked = client.post(
        "/api/auth/login", json={"email": user["email"], "password": user["password"]}
    )
    assert locked.status_code == 423
    assert "Retry-After" in locked.headers


def test_me_requires_a_valid_token(client, make_user):
    user = make_user()

    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401

    ok = client.get("/api/auth/me", headers=user["headers"])
    assert ok.status_code == 200
    assert ok.json()["email"] == user["email"]


def test_token_signed_with_another_secret_is_rejected(client):
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": "1",
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "iat": int(now.timestamp()),
            "jti": "forged",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        "a-different-secret-that-is-long-enough-to-sign",
        algorithm="HS256",
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_expired_token_is_rejected(client):
    past = datetime.now(UTC) - timedelta(minutes=5)
    expired = jwt.encode(
        {
            "sub": "1",
            "exp": int(past.timestamp()),
            "iat": int((past - timedelta(minutes=10)).timestamp()),
            "jti": "expired",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_gender_accepts_only_the_three_options(client, make_user):
    """Gender is a closed set: Male, Female, Other (or null to clear it)."""
    user = make_user()

    for value in ("Male", "Female", "Other"):
        ok = client.patch("/api/auth/me", headers=user["headers"], json={"gender": value})
        assert ok.status_code == 200, ok.text
        assert ok.json()["gender"] == value

    # Free text — including a lower-case spelling — is rejected, not coerced.
    for value in ("female", "MALE", "nonbinary", ""):
        bad = client.patch("/api/auth/me", headers=user["headers"], json={"gender": value})
        assert bad.status_code == 422, f"{value!r} -> {bad.status_code}: {bad.text}"

    # An explicit null clears it, and the change is visible on the flat user shape.
    cleared = client.patch("/api/auth/me", headers=user["headers"], json={"gender": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["gender"] is None
    assert client.get("/api/auth/me", headers=user["headers"]).json()["gender"] is None


def test_gender_is_validated_on_profile_creation(client):
    """The same closed set applies to ``POST /api/profiles``."""
    body = _register(client, email=f"gender-create-{uuid4().hex[:8]}@example.com").json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    bad = client.post("/api/profiles", headers=headers, json={"first_name": "Asha", "gender": "Rather not say"})
    assert bad.status_code == 422, bad.text

    # The rejected attempt wrote nothing, so the one profile slot is still free.
    good = client.post("/api/profiles", headers=headers, json={"first_name": "Asha", "gender": "Other"})
    assert good.status_code == 201, good.text
    assert good.json()["gender"] == "Other"
