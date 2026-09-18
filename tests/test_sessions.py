"""Refresh-token rotation, revocation on logout, password changes, audit trail."""

from app.database.database import SessionLocal
from app.database.models import AuditLog, RefreshToken
from app.services.auth import hash_refresh_token


def test_refresh_rotates_the_token_and_detects_reuse(client, make_user):
    user = make_user()

    first = client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]})
    assert first.status_code == 200, first.text
    rotated = first.json()["refresh_token"]
    assert rotated != user["refresh_token"]

    # Replaying the consumed token is treated as a leak and kills the chain.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": rotated}).status_code == 401


def test_unknown_refresh_token_is_rejected(client):
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "x" * 40}).status_code == 401


def test_logout_revokes_the_refresh_token(client, make_user):
    user = make_user()

    logout = client.post(
        "/api/v1/auth/logout",
        headers=user["headers"],
        json={"refresh_token": user["refresh_token"]},
    )
    assert logout.status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]}).status_code == 401


def test_change_password_verifies_current_and_revokes_sessions(client, make_user):
    user = make_user()

    wrong = client.post(
        "/api/v1/auth/change-password",
        headers=user["headers"],
        json={"current_password": "NotMyPassword1", "new_password": "Br4ndNewPass"},
    )
    assert wrong.status_code == 400

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=user["headers"],
        json={"current_password": user["password"], "new_password": "Br4ndNewPass"},
    )
    assert changed.status_code == 200

    # Existing sessions are revoked and the previous password stops working.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]}).status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]}).status_code
        == 401
    )
    assert (
        client.post("/api/v1/auth/login", json={"email": user["email"], "password": "Br4ndNewPass"}).status_code
        == 200
    )


def test_refresh_tokens_are_stored_hashed(client, make_user):
    user = make_user()
    digest = hash_refresh_token(user["refresh_token"])

    with SessionLocal() as db:
        stored = db.query(RefreshToken).filter(RefreshToken.token_hash == digest).one()
        assert stored.token_hash != user["refresh_token"]
        assert stored.revoked_at is None


def test_security_events_are_audited(client, make_user):
    user = make_user()
    client.post("/api/v1/auth/login", json={"email": user["email"], "password": "WrongPass123"})
    client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})

    with SessionLocal() as db:
        actions = {row.action for row in db.query(AuditLog).all()}

    assert {"user.registered", "auth.login_failed", "auth.login_succeeded"} <= actions
