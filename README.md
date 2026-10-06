# Clinic Agent Backend

FastAPI backend for a clinic assistant that answers clinic questions, checks
doctor availability, books appointments, and manages patient/staff/admin access.

## Features

- AI chat workflow for FAQ, RAG, appointment booking, and medical search
- Doctor schedules, availability lookup, and appointment management
- JWT authentication with refresh tokens and role-based access control
- Patient self-service endpoints for viewing, editing, and cancelling bookings
- Long-term assistant memory with user controls
- PostgreSQL support with Alembic migrations

## Multi-Agent Flow

Clinic Agent uses a LangGraph workflow as a small multi-agent system. The first
node classifies the user message, then routes it to the focused agent or tool
path that can answer safely.

```text
User message
    |
    v
Authenticated chat endpoint
    |
    v
Load conversation state, recent history, summary, and long-term memories
    |
    v
LangGraph: route_intent
    |
    +--> RAG Agent
    |       - answers doctor/clinic knowledge questions from clinic documents
    |       - returns source chunks for grounded responses
    |
    +--> Availability Agent
    |       - lists doctors and open slots
    |       - checks working days, breaks, leaves, and booked slots
    |
    +--> Booking Agent
    |       - collects missing appointment fields step by step
    |       - validates doctor, date, time, patient details, and confirmation
    |       - books through the appointment service
    |
    +--> Medical Search Agent
    |       - handles general health questions with medical web search
    |       - keeps the answer separate from clinic booking facts
    |
    +--> Fallback / Out-of-scope Handler
    |       - replies to greetings and assistant identity questions
    |       - rejects non-clinic, non-healthcare requests
    |
    +--> FAQ Agent
            - answers approved clinic questions from data/clinic/faq.json
            - falls back to document RAG when FAQ confidence is low
```

After an agent responds, the API saves the turn, updates conversation state, and
extracts durable memories in the background when appropriate.

## Tech Stack

- Python 3.13
- FastAPI and Uvicorn
- SQLAlchemy and Alembic
- PostgreSQL
- LangGraph, LangChain, Google Gemini, FastEmbed, FAISS
- uv for dependency management
- pytest and Ruff

## Requirements

- Python 3.13
- uv
- Docker and Docker Compose
- Google AI Studio API key for LLM/RAG answers

## Quick Start With Docker

Create an environment file:

```bash
cp .env.example .env
```

Update at least:

```env
GOOGLE_API_KEY=your-google-api-key
JWT_SECRET_KEY=replace-with-a-long-random-secret
```

Start the backend and database:

```bash
docker compose up -d --build
```

The API is available at:

- `http://localhost:8000`
- `http://localhost:8000/docs`
- `http://localhost:8000/health/live`

Docker Compose starts:

- `backend` on port `8000`
- `db` on host port `5434`

## Local Development

Install dependencies:

```bash
uv sync
```

Copy and edit the environment file:

```bash
cp .env.example .env
```

Run migrations:

```bash
uv run alembic upgrade head
```

Start the API:

```bash
uv run uvicorn app.main:app --reload
```

## Configuration

Important environment variables:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy database URL |
| `GOOGLE_API_KEY` | Google Gemini API key |
| `GOOGLE_AI_MODEL` | Gemini model used by the agents |
| `JWT_SECRET_KEY` | Secret used to sign access tokens |
| `CLINIC_TIMEZONE` | Timezone used for schedules and past-slot checks |
| `ALLOWED_ORIGINS` | Frontend origins allowed by CORS |
| `ENABLE_DOCS` | Enables `/docs`, `/redoc`, and `/openapi.json` |
| `CREATE_TABLES_ON_STARTUP` | Development-only table creation fallback |

Use `.env.example` as the source of supported settings.

## First Admin

Public registration creates patient accounts only. Create the first admin from
the server side:

```bash
export BOOTSTRAP_ADMIN_EMAIL=admin@clinic.com
export BOOTSTRAP_ADMIN_PASSWORD='Str0ngPassw0rd'
export BOOTSTRAP_ADMIN_NAME='Clinic Admin'
uv run python -m app.cli bootstrap-admin
```

After that, admins can create staff/admin users from the Team page.

## Migrations

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
uv run alembic downgrade -1
```

## Tests and Linting

```bash
uv run pytest
uv run ruff check app tests
```

## Main API Areas

- `GET /health/live` and `GET /health/ready`
- `/api/auth/*` for registration, login, refresh, logout, users, and roles
- `/chat` and `/rag` for assistant conversations
- `/doctor-schedule/*` for doctor schedules
- `/availability/*` for open slots
- `/appointments/*` for bookings and clinic appointment management
- `/appointments/me*` for patient-owned appointment management
- `/api/memories/*` for long-term memory controls

Routes are exposed both unversioned and under `/api` where supported by the
backend router.
