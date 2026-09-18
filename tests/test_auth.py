"""Registration, login, lockout and access-token validation."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import settings

DEFAULT_PASSWORD = "Sup3rSecret1"


def _register(client, email="new-user@example.com", password=DEFAULT_PASSWORD):
    return client.post(
        "/api/v1/auth/register",
        json={"full_name": "New User", "email": email, "password": password},
    )


def test_register_returns_tokens_and_profile(client):
    response = _register(client)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["expires_in"] == settings.access_token_expire_minutes * 60
    assert body["user"]["email"] == "new-user@example.com"
    assert body["user"]["role"] == "patient"
    assert "password" not in body["user"]


def test_register_rejects_duplicate_email(client):
    _register(client, email="duplicate@example.com")
    assert _register(client, email="duplicate@example.com").status_code == 409


@pytest.mark.parametrize("password", ["short1", "alllettersnodigit", "12345678901", "password"])
def test_register_enforces_password_policy(client, password):
    response = _register(client, email=f"weak-{password}@example.com", password=password)
    assert response.status_code == 422


def test_login_succeeds(client, make_user):
    user = make_user()
    response = client.post(
        "/api/v1/auth/login", json={"email": user["email"], "password": user["password"]}
    )
    assert response.status_code == 200
    assert response.json()["user"]["email"] == user["email"]


def test_login_failures_are_indistinguishable(client, make_user):
    user = make_user()

    wrong_password = client.post(
        "/api/v1/auth/login", json={"email": user["email"], "password": "WrongPass123"}
    )
    unknown_user = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "WrongPass123"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_account_locks_after_repeated_failures(client, make_user):
    user = make_user()

    for _ in range(settings.max_failed_login_attempts):
        attempt = client.post(
            "/api/v1/auth/login", json={"email": user["email"], "password": "WrongPass123"}
        )
        assert attempt.status_code == 401

    locked = client.post(
        "/api/v1/auth/login", json={"email": user["email"], "password": user["password"]}
    )
    assert locked.status_code == 423
    assert "Retry-After" in locked.headers


def test_me_requires_a_valid_token(client, make_user):
    user = make_user()

    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401

    ok = client.get("/api/v1/auth/me", headers=user["headers"])
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
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
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
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401