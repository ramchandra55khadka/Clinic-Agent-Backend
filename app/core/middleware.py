"""Cross-cutting HTTP middleware: request correlation, access logs, headers.

Every response carries the request id (echoing an inbound ``X-Request-ID`` when
present) so a frontend error can be traced to the exact backend log line.
"""

from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.core.logging import logger, set_request_id

#: Baseline hardening for an API (the frontend sets its own CSP, see next.config.ts).
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def register_middleware(app: FastAPI) -> None:
    # Only applied when explicit hosts are configured; "*" keeps dev frictionless.
    if settings.trusted_hosts and "*" not in settings.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))

    @app.middleware("http")
    async def observability_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        set_request_id(request_id)
        started = perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled error: {} {} ({:.0f}ms)",
                request.method,
                request.url.path,
                (perf_counter() - started) * 1000,
            )
            raise

        duration_ms = round((perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = str(duration_ms)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)

        logger.info(
            "{} {} -> {} in {}ms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
