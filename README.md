# Clinic Assistant — API

Agentic-AI backend for a clinic: doctor knowledge base (RAG), availability
lookup and appointment booking, exposed over HTTP and driven by a LangGraph
workflow. FastAPI + SQLAlchemy + Postgres, with JWT authentication, refresh-token
rotation, rate limiting and an audit trail.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 14+ (SQLite also works for local experiments)
- A Google AI Studio API key for LLM/RAG answers (`GOOGLE_API_KEY`)
- General medical web search uses keyless DuckDuckGo search; no search API key is required

## Quickstart

```bash
cp .env.example .env          # then edit: DATABASE_URL, GOOGLE_API_KEY, JWT_SECRET_KEY
uv sync                       # create the environment from uv.lock
uv run alembic upgrade head   # create/upgrade the schema
uv run uvicorn app.main:app --reload
```

Interactive docs are served at `/docs` while `ENABLE_DOCS` is true.

## Create The First Admin

Public sign-up always creates a `patient`. The first `admin` must be created from
the server side with the CLI, after migrations have run. Do not add a public
`/setup` route and do not send `role=admin` from registration.

### Local development

```bash
cp .env.example .env
uv sync
uv run alembic upgrade head

export BOOTSTRAP_ADMIN_EMAIL=admin@clinic.com
export BOOTSTRAP_ADMIN_PASSWORD='Str0ngPassw0rd'
export BOOTSTRAP_ADMIN_NAME='Clinic Admin'
uv run python -m app.cli bootstrap-admin
```

Now start the API and sign in with that email/password:

```bash
uv run uvicorn app.main:app --reload
```

### Docker Compose / production-shaped deploy

Set these values in `clinic-agent-backend/.env` or your production secret
manager before `docker compose up`:

```env
BOOTSTRAP_ADMIN_EMAIL=admin@clinic.com
BOOTSTRAP_ADMIN_PASSWORD=Str0ngPassw0rd
BOOTSTRAP_ADMIN_NAME=Clinic Admin
```

Then run from the repository root:

```bash
docker compose up --build
```

Compose runs the deployment in this order:

1. PostgreSQL becomes healthy
2. `alembic upgrade head` applies migrations
3. `python -m app.cli bootstrap-admin` creates the first admin if needed
4. The FastAPI server starts

### Safety Rules

- `bootstrap-admin` exits successfully and does nothing when the env vars are unset.
- `bootstrap-admin` does nothing once any active admin exists, so it is safe on every deploy.
- Passwords are validated with the same rules as the API.
- Invalid or reserved emails such as `*.local` / `*.test` are rejected.
- The action is written to `audit_log` with `actor_email="bootstrap"`.
- Store the bootstrap password in a secret manager for production; never commit it.

After the first admin exists, use the Team page to create staff/admin accounts.
For emergency CLI management:

```bash
uv run python -m app.cli create-user --email staff@clinic.com --password 'Str0ngPassw0rd' --name 'Clinic Staff' --role staff
uv run python -m app.cli set-role --email someone@clinic.com --role staff
```

`create-admin` and `promote-admin` remain CLI aliases for local recovery, but the
recommended production path is `bootstrap-admin` plus admin-managed onboarding.

Passwords must be at least 10 characters. Avoid reserved/special-use mail
domains (`*.local`, `*.test`, …) — they are rejected by e-mail validation.

The development database ships with these demo accounts —
`frontend-test@example.com` / `secret12345` (patient),
`staff@novacare.dev` / `Clinic@12345` (staff) and
`admin@novacare.dev` / `Clinic@12345` (admin).

## Configuration

Every setting is documented in `.env.example`. The ones that matter most:

| Variable | Purpose |
| --- | --- |
| `ENVIRONMENT` | `development` (default) or `production`; drives fail-fast validation |
| `DATABASE_URL` | `postgresql+psycopg2://user:pass@host:5432/clinicdb` |
| `JWT_SECRET_KEY` | HS256 signing key — **must** be ≥ 32 chars in production (`openssl rand -hex 32`) |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`, `BOOTSTRAP_ADMIN_NAME` | Optional deploy-time first-admin seed used by `python -m app.cli bootstrap-admin` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime (default 15) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh-token lifetime (default 14) |
| `MAX_FAILED_LOGIN_ATTEMPTS`, `LOCKOUT_MINUTES` | Per-account lockout policy |
| `RATE_LIMIT_ENABLED`, `LOGIN_RATE_LIMIT`, … | Per-IP limits on login/registration |
| `CLINIC_TIMEZONE` | Timezone for working-hours and past-slot checks (default `Asia/Kathmandu`) |
| `ALLOWED_ORIGINS`, `TRUSTED_HOSTS` | CORS and Host-header allowlists |
| `CREATE_TABLES_ON_STARTUP` | Development only; production uses Alembic |

Startup refuses to boot in production when the JWT secret is weak, CORS is a
wildcard or `GOOGLE_API_KEY` is missing.

## Long-Term Memory

The assistant now uses a hybrid memory approach:

- `conversation` stores one chat thread per signed-in user/session.
- `conversation_message` stores the user and assistant turns for auditability and future summarization.
- `long_term_memory` stores only durable preferences/facts, such as preferred appointment times or reminder style.
- Embeddings use BGE (`BAAI/bge-small-en-v1.5`) through FastEmbed for semantic retrieval.
- Storage is currently JSON text for SQLite compatibility; PostgreSQL deployments can move this column to `pgvector` once the extension is installed.

The chat route retrieves relevant memories before running LangGraph, then saves the new turn and schedules extraction with FastAPI `BackgroundTasks`. This keeps the architecture ready for Celery/Redis without requiring the queue during local development.

User memory controls:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/memories/` | List the signed-in user's active memories |
| `DELETE` | `/api/memories/{memory_id}` | Soft-delete one memory owned by the user |
| `DELETE` | `/api/memories/` | Clear all active memories owned by the user |

Memory extraction deliberately avoids saving every message. It only stores durable, reusable information and ignores one-off symptoms, temporary appointment details and sensitive medical conclusions.

For production, install pgvector in PostgreSQL before converting the embedding column to a native vector type. The migration enables the extension automatically when it is available and skips it cleanly when the local Postgres image does not include pgvector.

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
- **Roles** — three-tier, enforced on every route by the backend (the client
  value is only cosmetic):
  - `patient` — default on registration; chats, checks availability, books and
    manages their own appointments (`/appointments/me*`)
  - `staff` — clinic front desk; everything a patient can do, plus full
    management of doctors and their schedules/availability
  - `admin` — superset of staff; additionally manages user accounts and roles
    (`/api/auth/users*`)
  Bootstrap the first admin with `python -m app.cli bootstrap-admin`; do not expose a public setup endpoint.
- **Audit trail** — sign-ins, failures, lockouts, refreshes, logouts, password
  changes and bookings are recorded in `audit_log`.

## API surface

| Method | Path | Access |
| --- | --- | --- |
| `GET` | `/`, `/health`, `/health/live`, `/health/ready` | public (ready checks the DB) |
| `POST` | `/api/auth/register`, `/api/auth/login` | public, rate limited |
| `POST` | `/api/auth/refresh`, `/api/auth/logout` | refresh token |
| `GET` | `/api/auth/me` | authenticated |
| `POST` | `/api/auth/change-password` | authenticated |
| `GET` | `/api/memories/` | authenticated |
| `DELETE` | `/api/memories/{memory_id}`, `/api/memories/` | authenticated |
| `GET` | `/api/auth/users` | admin |
| `POST` | `/api/auth/users` (create staff/admin) | admin |
| `PATCH` | `/api/auth/users/{id}/role`, `/api/auth/users/{id}/active` | admin |
| `POST` | `/chat`, `/rag` | authenticated |
| `GET` | `/doctor-schedule/`, `/doctor-schedule/{id}` | authenticated |
| `POST/PUT/DELETE` | `/doctor-schedule/…` | staff or admin |
| `POST` | `/appointments/` | authenticated (unique slot per doctor) |
| `GET` | `/appointments/me` | authenticated — the caller's own bookings |
| `GET` | `/appointments/me/{id}` | authenticated — 404 unless the booking is the caller's |
| `PUT` | `/appointments/me/{id}` | authenticated — edit details or reschedule (re-checks the slot) |
| `POST` | `/appointments/me/{id}/cancel` | authenticated — cancels and frees the slot |
| `GET` | `/appointments/{doctor_id}` | staff or admin |
| `POST` | `/availability/` | authenticated |
| `GET` | `/availability/{doctor_id}/{date}` | authenticated |
| `POST` | `/mcp/check-availability`, `/mcp/book-appointment` | authenticated |

Every route is served both unversioned and under `/api`.

## Tests and linting

```bash
uv run pytest          # auth, authorization matrix, booking rules, health
uv run ruff check app tests
```

Tests run against a throwaway SQLite file and never touch the configured
Postgres database.

## Deployment

```bash
docker compose up --build        # from the repository root: db + migrate + api + web
```

The container runs as an unprivileged user. Compose applies `alembic upgrade head` in a
one-shot `migrate` service, then runs one-shot `bootstrap-admin`, then starts the API. It exposes:

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
- Memory extraction currently runs through FastAPI `BackgroundTasks`; move it to
  Celery + Redis before real production traffic so chat responses are not tied to
  extraction work.
- Doctor/RAG chat answers require a valid `GOOGLE_API_KEY`; without it the workflow returns
  retrieved knowledge without an LLM-generated answer. General medical web search uses DuckDuckGo without a key; if `GOOGLE_API_KEY` is missing, it returns source links instead of an LLM summary.