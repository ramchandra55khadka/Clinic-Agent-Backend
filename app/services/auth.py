"""Password hashing, access tokens and refresh tokens.

Access tokens are short-lived HS256 JWTs signed with ``JWT_SECRET_KEY`` and
validated with PyJWT (issuer/audience/expiry/`jti` all checked). Refresh tokens
are opaque 384-bit random strings; only their SHA-256 hash is stored, so a
database leak does not hand out sessions.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import settings

PBKDF2_ITERATIONS = 120_000
REFRESH_TOKEN_BYTES = 48
MIN_PASSWORD_LENGTH = 8

#: Deliberately tiny denylist — a full breach list belongs in a dedicated check.
COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "qwertyui",
        "qwerty123",
        "letmein123",
        "iloveyou",
        "admin123",
        "changeme",
        "welcome1",
        "clinic123",
        "test1234",
    }
)


class TokenError(Exception):
    """Raised when an access token is missing, malformed, expired or forged."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    """Policy violations for a candidate password (empty list means acceptable)."""
    problems: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("is too common")
    if not any(char.isalpha() for char in password):
        problems.append("must contain a letter")
    if not any(char.isdigit() for char in password):
        problems.append("must contain a digit")
    return problems


# --------------------------------------------------------------------------- #
# Access tokens
# --------------------------------------------------------------------------- #

def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(16),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Validated claims, or :class:`TokenError` describing why the token is unusable."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except ExpiredSignatureError as exc:
        raise TokenError("expired") from exc
    except InvalidTokenError as exc:
        raise TokenError("invalid") from exc


def access_token_expires_in() -> int:
    """Seconds a freshly issued access token stays valid."""
    return settings.access_token_expire_minutes * 60


# --------------------------------------------------------------------------- #
# Refresh tokens
# --------------------------------------------------------------------------- #

def generate_refresh_token() -> tuple[str, str]:
    """Returns ``(raw_token, token_hash)`` — only the hash is persisted."""
    raw = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)


def is_expired(expires_at: datetime) -> bool:
    """Timezone-safe expiry comparison for values read back from the database."""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)
