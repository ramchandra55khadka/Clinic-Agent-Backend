"""Database engine, session factory and FastAPI session dependency.

Pooling is tuned for a real Postgres deployment: ``pool_pre_ping`` discards
connections dropped by the server, ``pool_recycle`` avoids reusing connections a
proxy has already closed, and the pool is bounded so a traffic spike cannot
exhaust database connections. SQLite (tests) keeps its single-thread flag.
"""

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base

__all__ = ["Base", "DATABASE_URL", "SessionLocal", "engine", "get_db", "init_db"]

DATABASE_URL = settings.database_url

_IS_SQLITE = DATABASE_URL.startswith("sqlite")

_engine_options: dict[str, Any] = {"pool_pre_ping": True, "echo": False}
if _IS_SQLITE:
    _engine_options["connect_args"] = {"check_same_thread": False}
else:
    _engine_options.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_timeout=settings.db_pool_timeout_seconds,
    )

engine = create_engine(DATABASE_URL, **_engine_options)

# Session factory: no autocommit/autoflush so transactions stay explicit.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency yielding a session and always closing it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Creates missing tables. Development convenience only — use Alembic in production."""
    import app.models  # noqa: F401  (registers every model on Base.metadata)

    Base.metadata.create_all(bind=engine)
