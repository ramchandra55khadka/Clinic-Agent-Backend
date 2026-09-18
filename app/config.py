"""Application configuration.

Settings are read once at import. ``Settings.validate()`` fails fast when a
production deployment is unsafe (default/weak JWT secret, wildcard CORS, an
unknown timezone, …) so the process refuses to start rather than issue
forgeable tokens.
"""

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()

DEVELOPMENT_ENVIRONMENTS = {"development", "dev", "local", "test", "testing"}
DEFAULT_JWT_SECRET = "change-me-in-production"
MIN_JWT_SECRET_LENGTH = 32


class ConfigurationError(RuntimeError):
    """Raised when the process must not start with the current environment."""


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {value!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _list_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Clinic Assistant API")
    environment: str = os.getenv("ENVIRONMENT", "development")

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./clinic_agent.db")
    db_pool_size: int = _int_env("DB_POOL_SIZE", 5)
    db_max_overflow: int = _int_env("DB_MAX_OVERFLOW", 10)
    db_pool_recycle_seconds: int = _int_env("DB_POOL_RECYCLE_SECONDS", 1800)
    db_pool_timeout_seconds: int = _int_env("DB_POOL_TIMEOUT_SECONDS", 30)
    google_api_key: str | None = os.getenv("GOOGLE_API_KEY")
    chunk_size: int = _int_env("CHUNK_SIZE", 800)
    chunk_overlap: int = _int_env("CHUNK_OVERLAP", 120)

    smtp_host: str | None = os.getenv("SMTP_HOST")
    smtp_port: int = _int_env("SMTP_PORT", 587)
    smtp_username: str | None = os.getenv("SMTP_USERNAME")
    smtp_password: str | None = os.getenv("SMTP_PASSWORD")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "no-reply@clinic.local")
    smtp_use_tls: bool = _bool_env("SMTP_USE_TLS", True)
    email_enabled: bool = _bool_env("EMAIL_ENABLED", False)

    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", DEFAULT_JWT_SECRET)
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "clinic-agent")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "clinic-agent-clients")
    access_token_expire_minutes: int = _int_env("ACCESS_TOKEN_EXPIRE_MINUTES", 15)
    refresh_token_expire_days: int = _int_env("REFRESH_TOKEN_EXPIRE_DAYS", 14)

    max_failed_login_attempts: int = _int_env("MAX_FAILED_LOGIN_ATTEMPTS", 5)
    lockout_minutes: int = _int_env("LOCKOUT_MINUTES", 15)
    rate_limit_enabled: bool = _bool_env("RATE_LIMIT_ENABLED", True)
    login_rate_limit: int = _int_env("LOGIN_RATE_LIMIT", 10)
    login_rate_window_seconds: int = _int_env("LOGIN_RATE_WINDOW_SECONDS", 300)
    register_rate_limit: int = _int_env("REGISTER_RATE_LIMIT", 5)
    register_rate_window_seconds: int = _int_env("REGISTER_RATE_WINDOW_SECONDS", 3600)

    clinic_timezone: str = os.getenv("CLINIC_TIMEZONE", "Asia/Kathmandu")
    allowed_origins: tuple[str, ...] = _list_env(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    trusted_hosts: tuple[str, ...] = _list_env("TRUSTED_HOSTS", "*")

    api_v1_prefix: str = os.getenv("API_V1_PREFIX", "/api/v1")
    enable_docs: bool = _bool_env(
        "ENABLE_DOCS",
        os.getenv("ENVIRONMENT", "development") in DEVELOPMENT_ENVIRONMENTS,
    )
    create_tables_on_startup: bool = _bool_env(
        "CREATE_TABLES_ON_STARTUP",
        os.getenv("ENVIRONMENT", "development") in DEVELOPMENT_ENVIRONMENTS,
    )
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_json: bool = _bool_env(
        "LOG_JSON",
        os.getenv("ENVIRONMENT", "development") not in DEVELOPMENT_ENVIRONMENTS,
    )

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() not in DEVELOPMENT_ENVIRONMENTS

    @property
    def clinic_tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.clinic_timezone)

    def warnings(self) -> list[str]:
        """Non-fatal configuration smells worth surfacing at startup."""
        notes: list[str] = []
        if self.is_production and self.create_tables_on_startup:
            notes.append(
                "CREATE_TABLES_ON_STARTUP is enabled in production; run `alembic upgrade head` instead."
            )
        if not self.email_enabled:
            notes.append("EMAIL_ENABLED is false: appointment confirmations are skipped.")
        if not self.google_api_key:
            notes.append("GOOGLE_API_KEY is missing: chat/RAG answers fall back to retrieval only.")
        return notes

    def validate(self) -> None:
        """Raise :class:`ConfigurationError` when the deployment is unsafe."""
        problems: list[str] = []

        if self.access_token_expire_minutes < 1:
            problems.append("ACCESS_TOKEN_EXPIRE_MINUTES must be >= 1")
        if self.refresh_token_expire_days < 1:
            problems.append("REFRESH_TOKEN_EXPIRE_DAYS must be >= 1")
        if self.max_failed_login_attempts < 3:
            problems.append("MAX_FAILED_LOGIN_ATTEMPTS must be >= 3")
        if self.lockout_minutes < 1:
            problems.append("LOCKOUT_MINUTES must be >= 1")
        if self.jwt_algorithm != "HS256":
            problems.append(f"JWT_ALGORITHM {self.jwt_algorithm!r} is not supported (use HS256)")

        try:
            ZoneInfo(self.clinic_timezone)
        except ZoneInfoNotFoundError:
            problems.append(f"CLINIC_TIMEZONE {self.clinic_timezone!r} is not a known timezone")

        if self.is_production:
            secret = self.jwt_secret_key or ""
            if secret == DEFAULT_JWT_SECRET:
                problems.append("JWT_SECRET_KEY is still the default value")
            elif len(secret) < MIN_JWT_SECRET_LENGTH:
                problems.append(f"JWT_SECRET_KEY must be at least {MIN_JWT_SECRET_LENGTH} characters")
            if any(origin == "*" for origin in self.allowed_origins):
                problems.append("ALLOWED_ORIGINS must list explicit origins in production")
            if self.google_api_key is None:
                problems.append("GOOGLE_API_KEY is required in production")

        if problems:
            raise ConfigurationError(
                f"Invalid configuration for environment {self.environment!r}: " + "; ".join(problems)
            )


settings = Settings()

GOOGLE_API_KEY = settings.google_api_key
CHUNK_SIZE = settings.chunk_size
CHUNK_OVERLAP = settings.chunk_overlap
DATABASE_URL = settings.database_url
