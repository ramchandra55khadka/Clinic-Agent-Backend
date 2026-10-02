"""Structured logging.

Production emits one JSON object per line (ready for Loki/CloudWatch/ELK);
development keeps loguru's human-readable output. Every record carries the
request id of the request being served.
"""

import sys
from contextvars import ContextVar

from loguru import logger

from app.core.config import settings

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | "
    "<cyan>{extra[request_id]}</cyan> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


def configure_logging() -> None:
    """Installs a single stdout sink and removes loguru's default handler."""
    logger.remove()

    def patcher(record: dict) -> None:
        record["extra"].setdefault("request_id", _request_id.get())

    logger.configure(patcher=patcher)
    logger.add(
        sys.stdout,
        level=settings.log_level.upper(),
        serialize=settings.log_json,
        backtrace=False,
        diagnose=False,
        enqueue=False,
    )


__all__ = ["configure_logging", "get_request_id", "set_request_id", "logger"]