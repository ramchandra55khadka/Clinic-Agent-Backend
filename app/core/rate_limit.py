"""Fixed-window rate limiting for the auth endpoints.

The store is in-process, which is enough for a single worker and for tests. A
multi-worker or multi-container deployment must swap :class:`WindowStore` for a
shared backend (Redis ``INCR`` + ``EXPIRE``); the dependency interface stays the
same. Set ``RATE_LIMIT_ENABLED=false`` to disable (used by the test suite).
"""

import threading
import time
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from app.config import settings


class WindowStore:
    """Counts hits per key inside a rolling fixed window."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, scope: str, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Registers a hit; returns ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        bucket = (scope, key)
        with self._lock:
            count, reset_at = self._hits.get(bucket, (0, now + window_seconds))
            if now >= reset_at:
                count, reset_at = 0, now + window_seconds
            count += 1
            self._hits[bucket] = (count, reset_at)
            # Opportunistic cleanup keeps the dict from growing without bound.
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if v[1] > now}
            if count > limit:
                return False, max(1, int(reset_at - now))
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


store = WindowStore()


def rate_limit(
    *,
    scope: str,
    limit: int,
    window_seconds: int,
    key: Callable[[Request], str],
):
    """Builds a FastAPI dependency enforcing ``limit`` requests per window."""

    def dependency(request: Request) -> None:
        if not settings.rate_limit_enabled or limit <= 0:
            return
        allowed, retry_after = store.hit(scope, key(request), limit, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


def ip_key(request: Request) -> str:
    from app.dependencies.auth import client_ip

    return client_ip(request) or "unknown"