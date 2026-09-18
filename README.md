# Clinic Assistant — API

Agentic-AI backend for a clinic: doctor knowledge base (RAG), availability
lookup and appointment booking, exposed over HTTP and driven by a LangGraph
workflow. FastAPI + SQLAlchemy + Postgres, with JWT authentication, refresh-token
rotation, rate limiting and an audit trail.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 14+ (SQLite also works for local experiments)
- A Google AI Studio API key for LLM answers (`GOOGLE_API_KEY`)

## Quickstart

```bash
cp .env.example .env          # then edit: DATABASE_URL, GOOGLE_API_KEY, JWT_SECRET_KEY
uv sync                       # create the environment from uv.lock
uv run alembic upgrade head   # create/upgrade the schema
uv run uvicorn app.main:app --reload
```

Interactive docs are served at `/docs` while `ENABLE_DOCS` is true.

Create the first administrator (registration always creates patients):

```bash
uv run python -m app.cli create-admin --email admin@clinic.local --password 'Str0ngPassw0rd' --name 'Clinic Admin'
uv run python -m app.cli promote-admin --email someone@clinic.local
```

## Configuration

Every setting is documented in `.env.example`. The ones that matter most:

| Variable | Purpose |
| --- | --- |
| `ENVIRONMENT` | `development` (default) or `production`; drives fail-fast validation |
| `DATABASE_URL` | `postgresql+psycopg2://user:pass@host:5432/clinicdb` |
| `JWT_SECRET_KEY` | HS256 signing key — **must** be ≥ 32 chars in production (`openssl rand -hex 32`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime (default 15) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh-token lifetime (default 14) |
| `MAX_FAILED_LOGIN_ATTEMPTS`, `LOCKOUT_MINUTES` | Per-account lockout policy |
| `RATE_LIMIT_ENABLED`, `LOGIN_RATE_LIMIT`, … | Per-IP limits on login/registration |
| `CLINIC_TIMEZONE` | Timezone for working-hours and past-slot checks (default `Asia/Kathmandu`) |
| `ALLOWED_ORIGINS`, `TRUSTED_HOSTS` | CORS and Host-header allowlists |
| `CREATE_TABLES_ON_STARTUP` | Development only; production uses Alembic |

Startup refuses to boot in production when the JWT secret is weak, CORS is a
wildcard or `GOOGLE_API_KEY` is missing.

## Database migrations

Schema changes are managed by Alembic (`migrations/`), never by hand:

```bash
uv run alembic upgrade head                 # apply all migrations
uv run alembic revision --autogenerate -m "add x"   # create a new one
uv run alembic downgrade -1                 # roll back one step
```

Databases that predate Alembic (created with `create_all()`) must be stamped
once at the baseline before upgrading:

```bash
uv run alembic stamp 0001_initial
uv run alembic upgrade head
```

`0002_production_hardening` is written defensively (it inspects the schema
before adding anything), so running it against a partially-migrated database is
safe.

## Authentication model

- **Access token** — HS256 JWT (`sub`, `iat`, `nbf`, `exp`, `jti`, `iss`, `aud`),
  signed with `JWT_SECRET_KEY`, short-lived (15 min by default) and verified by
  PyJWT on every protected request.
- **Refresh token** — 384-bit random value, stored only as a SHA-256 hash.
  Rotated on every use; reusing a rotated token is treated as a leak and revokes
  the whole session chain. Revoked on logout and on password change.
- **Lockout / rate limits** — repeated failures lock the account for
  `LOCKOUT_MINUTES`; login and registration are additionally limited per IP.
- **Roles** — `patient` (default on registration) and `admin` (schedule and
  appointment administration). Bootstrap with `python -m app.cli`.
- **Audit trail** — sign-ins, failures, lockouts, refreshes, logouts, password
  changes and bookings are recorded in `audit_log`.

## API surface

| Method | Path | Access |
| --- | --- | --- |
| `GET` | `/`, `/health`, `/health/live`, `/health/ready` | public (ready checks the DB) |
| `POST` | `/api/v1/auth/register`, `/api/v1/auth/login` | public, rate limited |
| `POST` | `/api/v1/auth/refresh`, `/api/v1/auth/logout` | refresh token |
| `GET` | `/api/v1/auth/me` | authenticated |
| `POST` | `/api/v1/auth/change-password` | authenticated |
| `POST` | `/chat`, `/rag` | authenticated |
| `GET` | `/doctor-schedule/`, `/doctor-schedule/{id}` | authenticated |
| `POST/PUT/DELETE` | `/doctor-schedule/…` | admin |
| `POST` | `/appointments/` | authenticated (unique slot per doctor) |
| `GET` | `/appointments/{doctor_id}` | admin |
| `POST` | `/availability/` | authenticated |
| `GET` | `/availability/{doctor_id}/{date}` | authenticated |
| `POST` | `/mcp/check-availability`, `/mcp/book-appointment` | authenticated |

Every route is served both unversioned and under `/api/v1`.

## Tests and linting

```bash
uv run pytest          # 65+ tests: auth, authorization matrix, booking rules, health
uv run ruff check app tests
```

Tests run against a throwaway SQLite file and never touch the configured
Postgres database.

## Deployment

```bash
docker compose up --build        # from the repository root: db + migrate + api + web
```

The container runs as an unprivileged user, applies `alembic upgrade head` in a
one-shot `migrate` service before the API starts, and exposes:

- `GET /health/live` — process liveness (no dependencies)
- `GET /health/ready` — verifies the database, returns 503 when unavailable

Operational notes:

- Terminate TLS at a reverse proxy and forward `X-Forwarded-*`; the container
  already runs uvicorn with `--proxy-headers`.
- `LOG_JSON=true` in production emits one JSON object per line, each carrying the
  request id returned in the `X-Request-ID` response header.
- Set `ALLOWED_ORIGINS`, `TRUSTED_HOSTS`, `ENABLE_DOCS=false` and a strong
  `JWT_SECRET_KEY` for production.

### Known limitations / next steps

- Rate limiting is per-process; move `app/core/rate_limit.py` to Redis before
  running multiple workers or replicas.
- The frontend CSP still needs `'unsafe-inline'` for Next.js' bootstrap scripts;
  a nonce-based policy is the next hardening step.
- Appointment confirmation emails are sent by a background task; at higher volume
  move them to an outbox/queue with retries.
- Chat answers require a valid `GOOGLE_API_KEY`; without it the workflow returns
  retrieved knowledge without an LLM-generated answer.