# syntax=docker/dockerfile:1
#
# Production image for the clinic-agent API.
#   docker build -t clinic-agent-api .
#   docker run --env-file .env -p 8000:8000 clinic-agent-api

# ---------------------------------------------------------------- builder ----
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Only the lockfile + manifest first, so the dependency layer is cached.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Application code, migrations and the RAG assets (PDFs + prebuilt index).
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini main.py README.md ./
COPY docs ./docs
COPY vector_db ./vector_db
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------- runtime ----
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Never run the API as root.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app

USER appuser
EXPOSE 8000

# Liveness only: it must not fail because a dependency is unavailable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4)"

# --proxy-headers honours X-Forwarded-* from a trusted reverse proxy
# (FORWARDED_ALLOW_IPS controls which peers are trusted; default 127.0.0.1).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]