import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEV_ENVS = {"development", "dev", "local", "test", "testing"}
TRUE_VALUES = {"1", "true", "yes", "on"}

DOCS_DIR = Path(os.getenv("DOCS_DIR", "data")).expanduser()
PERSIST_DIR = Path(os.getenv("PERSIST_DIR", "vector_db/faiss")).expanduser()
FAQ_PATH = Path(os.getenv("FAQ_PATH", "data/clinic/faq.json")).expanduser()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDING_PREFIX = (
    "Represent this sentence for searching relevant passages: "
    if "bge" in EMBEDDING_MODEL.lower() and "-en" in EMBEDDING_MODEL.lower()
    else ""
)


@dataclass(frozen=True)
class Settings:
    environment: str = ENVIRONMENT
    app_name: str = os.getenv("APP_NAME", "Clinic Assistant API")
    api_prefix: str = os.getenv("API_PREFIX", "/api")

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./clinic_agent.db")
    db_pool_size: int = int(os.getenv("DB_POOL_SIZE", 5))
    db_max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", 10))
    db_pool_recycle_seconds: int = int(os.getenv("DB_POOL_RECYCLE_SECONDS", 1800))
    db_pool_timeout_seconds: int = int(os.getenv("DB_POOL_TIMEOUT_SECONDS", 30))

    google_api_key: str | None = os.getenv("GOOGLE_API_KEY")
    google_ai_model: str = os.getenv("GOOGLE_AI_MODEL", "gemini-2.5-flash")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", 0.2))
    llm_request_delay_seconds: float = float(
        os.getenv("LLM_REQUEST_DELAY_SECONDS", 2.0 if ENVIRONMENT.lower() in {"development", "dev", "local"} else 0.0)
    )

    docs_dir: str = str(DOCS_DIR if DOCS_DIR.is_absolute() else PROJECT_ROOT / DOCS_DIR)
    persist_dir: str = str(PERSIST_DIR if PERSIST_DIR.is_absolute() else PROJECT_ROOT / PERSIST_DIR)
    faq_path: str = str(FAQ_PATH if FAQ_PATH.is_absolute() else PROJECT_ROOT / FAQ_PATH)
    chunk_size: int = int(os.getenv("CHUNK_SIZE", 800))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", 120))
    embedding_model: str = EMBEDDING_MODEL
    embedding_query_prefix: str = os.getenv("EMBEDDING_QUERY_PREFIX", EMBEDDING_PREFIX)
    retrieval_candidates: int = int(os.getenv("RETRIEVAL_CANDIDATES", 20))
    retrieval_min_score: float = float(os.getenv("RETRIEVAL_MIN_SCORE", 0.0))
    rag_rebuild_index: bool = os.getenv("RAG_REBUILD_INDEX", "false").lower() in TRUE_VALUES
    faq_similarity_threshold: float = float(os.getenv("FAQ_SIMILARITY_THRESHOLD", 0.45))
    faq_max_results: int = int(os.getenv("FAQ_MAX_RESULTS", 1))

    smtp_host: str | None = os.getenv("SMTP_HOST")
    smtp_port: int = int(os.getenv("SMTP_PORT", 587))
    smtp_username: str | None = os.getenv("SMTP_USERNAME")
    smtp_password: str | None = os.getenv("SMTP_PASSWORD")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "no-reply@clinic.local")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() in TRUE_VALUES
    email_enabled: bool = os.getenv("EMAIL_ENABLED", "false").lower() in TRUE_VALUES

    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "clinic-agent")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "clinic-agent-clients")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 15))
    refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 14))

    max_failed_login_attempts: int = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", 5))
    lockout_minutes: int = int(os.getenv("LOCKOUT_MINUTES", 15))
    rate_limit_enabled: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in TRUE_VALUES
    login_rate_limit: int = int(os.getenv("LOGIN_RATE_LIMIT", 10))
    login_rate_window_seconds: int = int(os.getenv("LOGIN_RATE_WINDOW_SECONDS", 300))
    register_rate_limit: int = int(os.getenv("REGISTER_RATE_LIMIT", 5))
    register_rate_window_seconds: int = int(os.getenv("REGISTER_RATE_WINDOW_SECONDS", 3600))

    clinic_timezone: str = os.getenv("CLINIC_TIMEZONE", "Asia/Kathmandu")
    allowed_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        if item.strip()
    )
    trusted_hosts: tuple[str, ...] = tuple(item.strip() for item in os.getenv("TRUSTED_HOSTS", "*").split(",") if item.strip())

    enable_docs: bool = os.getenv("ENABLE_DOCS", str(ENVIRONMENT in DEV_ENVS)).lower() in TRUE_VALUES
    create_tables_on_startup: bool = os.getenv("CREATE_TABLES_ON_STARTUP", str(ENVIRONMENT in DEV_ENVS)).lower() in TRUE_VALUES
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_json: bool = os.getenv("LOG_JSON", str(ENVIRONMENT not in DEV_ENVS)).lower() in TRUE_VALUES

    @property
    def is_production(self) -> bool:
        return self.environment.lower() not in DEV_ENVS

    @property
    def clinic_tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.clinic_timezone)

    def warnings(self) -> list[str]:
        notes = []
        if self.is_production and self.create_tables_on_startup:
            notes.append("CREATE_TABLES_ON_STARTUP is enabled in production; run `alembic upgrade head` instead.")
        if not self.email_enabled:
            notes.append("EMAIL_ENABLED is false: appointment confirmations are skipped.")
        if not self.google_api_key:
            notes.append("GOOGLE_API_KEY is missing: chat/RAG answers fall back to retrieval only.")
        return notes

    def validate(self) -> None:
        pass


settings = Settings()

GOOGLE_API_KEY = settings.google_api_key
GOOGLE_AI_MODEL = settings.google_ai_model
LLM_TEMPERATURE = settings.llm_temperature
LLM_REQUEST_DELAY_SECONDS = settings.llm_request_delay_seconds
CHUNK_SIZE = settings.chunk_size
CHUNK_OVERLAP = settings.chunk_overlap
DATABASE_URL = settings.database_url
