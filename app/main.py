"""FastAPI application factory.

Startup validates the configuration (refusing to boot with an unsafe production
setup), logs warnings for optional features and — in development only — creates
missing tables. Production schema changes go through Alembic
(``alembic upgrade head``).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, logger
from app.core.middleware import register_middleware
from app.database.database import init_db
from app.router import router as legacy_router
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    for note in settings.warnings():
        logger.warning(note)

    if settings.create_tables_on_startup:
        try:
            init_db()
        except Exception as exc:
            logger.error("Database initialization failed: {}", type(exc).__name__)
            raise

    logger.info(
        "Clinic Assistant API started (environment={}, docs={})",
        settings.environment,
        settings.enable_docs,
    )
    yield
    logger.info("Clinic Assistant API stopped")


def create_app() -> FastAPI:
    # Fail before accepting traffic when the configuration is unsafe.
    settings.validate()
    configure_logging()

    docs_enabled = settings.enable_docs
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    allow_credentials = "*" not in settings.allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    register_middleware(app)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(legacy_router)

    @app.get("/", tags=["health"])
    async def root():
        return {"message": "Clinic assistant agent API is running", "status": "healthy"}

    return app


app = create_app()