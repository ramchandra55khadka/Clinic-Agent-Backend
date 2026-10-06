# Backend Implementation Notes

This file keeps deeper working details out of the main README.

## Main Business Logic

The backend is centered on three clinic workflows: authenticated patient chat,
appointment scheduling, and staff/admin clinic management.

```text
Authenticated user
    |
    +--> Chat workflow
    |       - loads the user's conversation state, recent transcript, summary,
    |         and long-term memories
    |       - routes the message through the LangGraph clinic agent
    |       - saves the user and assistant messages
    |       - stores updated booking state for the conversation
    |       - extracts durable memories and refreshes summaries in the background
    |
    +--> Appointment workflow
    |       - checks doctor schedule, working days, leave date, break time,
    |         working hours, existing bookings, and past slots
    |       - creates, edits, reschedules, or cancels appointments
    |       - links chat-created bookings to the signed-in account
    |       - sends confirmation email in a background task
    |
    +--> Clinic management workflow
            - staff/admin manage doctor schedules and clinic appointments
            - admin manages users and roles
            - backend enforces every role check regardless of frontend UI state
```

Scheduling rules live in `app/services/availability.py` and
`app/services/appointments.py`:

- A doctor must have a schedule.
- The requested date must be one of the doctor's working days.
- The requested date must not match the doctor's leave date.
- The appointment must fit inside working hours.
- The appointment must not overlap break time.
- The appointment must not overlap another non-cancelled booking.
- Past dates/times are rejected in the clinic timezone.
- A database uniqueness constraint still protects the final slot write when two
  requests race.

Patient ownership is account-based. Patient self-service endpoints return 404
for appointments the caller does not own, so the API does not reveal whether
another patient's booking exists.

## Main Agent Workflow

The main assistant is a LangGraph workflow defined in
`app/ai/chat_workflow/graph.py`. The entry node is `route_intent`; it classifies
the message and sends it to one focused path.

```text
POST /chat
    |
    v
Load session state + user profile + memories + recent history + summary
    |
    v
Simple deterministic handlers
    - greetings and small talk
    - remembered-name questions
    - appointment history shortcuts
    - direct doctor database responses
    |
    v
LangGraph route_intent
    |
    +--> doctor_bio_node
    |       Uses the RAG agent over clinic documents for doctor/clinic details.
    |
    +--> availability_node
    |       Uses MCP-style tools to list doctors, check slots, and explain
    |       unavailable times.
    |
    +--> booking_node
    |       Maintains a step-by-step booking state, extracts missing fields,
    |       validates slot availability, asks for confirmation, and books.
    |
    +--> medical_web_node
    |       Uses the medical search agent for general healthcare questions.
    |
    +--> fallback_node / out_of_scope_node
    |       Handles identity/greeting responses and rejects unrelated requests.
    |
    +--> faq_node
            Uses the curated FAQ store for approved clinic facts.
            If no confident FAQ match exists, falls back to RAG.
```

Important behavior:

- Conversation state is saved as JSON per user/session. Booking can continue
  across multiple turns because the required field and partial booking are kept
  in that state.
- Recent transcript and rolling summary are added to the prompt so follow-ups
  like "is he free tomorrow?" can resolve earlier context.
- Long-term memories are used only for personalization and logistics. FAQ
  answers intentionally exclude memory context so stored preferences cannot
  override approved clinic facts.
- If RAG cannot produce a grounded answer, the assistant asks a clarifying
  question instead of guessing.

## Memory Flow

There are three separate memory-like mechanisms:

| Mechanism | Storage | Purpose |
| --- | --- | --- |
| Conversation state | `conversation.state_json` | Active workflow state, especially multi-turn booking |
| Transcript | `conversation_message` | Replayable user/assistant chat history |
| Long-term memory | `long_term_memory` | Durable patient preferences and facts |

Request flow:

```text
Before agent runs
    |
    +--> load conversation.state_json
    +--> load recent transcript window
    +--> load rolling conversation summary
    +--> load allowed long-term memories if memory is enabled

After agent responds
    |
    +--> save updated conversation.state_json
    +--> save user message
    +--> save assistant message
    +--> background: extract durable memories from the user message
    +--> background: compact older transcript turns into the rolling summary
```

Long-term memory is intentionally conservative:

- It stores slot-based values such as `name`, `preferred_time`, `language`,
  `preferred_doctor`, and `contact_preference`.
- One key has one current value per user; new values update the existing row.
- Medical terms are rejected, so symptoms, diagnoses, medicines, allergies,
  pregnancy, cancer, diabetes, and similar health content are not saved.
- One-off appointment details are not stored as long-term memory.
- Users can list, edit, delete, or clear their memories from the API/profile UI.
- If a user disables memory, retrieval and extraction are skipped.

Transcript summary keeps long conversations usable:

- The newest turns stay verbatim in the prompt.
- Older turns are folded into `conversation.summary`.
- If no LLM key is configured, summary fallback keeps a truncated text summary
  instead of losing context.

## Authentication And Roles

- Access tokens are HS256 JWTs signed with `JWT_SECRET_KEY`.
- Refresh tokens are random values stored only as SHA-256 hashes.
- Refresh tokens rotate on use; reuse of a rotated token revokes the session chain.
- Password changes and logout revoke active refresh tokens.
- Login and registration are rate limited.
- Repeated failed logins can lock an account.

Roles:

| Role | Access |
| --- | --- |
| `patient` | Chat, availability, booking, and own appointments |
| `staff` | Patient permissions plus doctor schedules and clinic appointments |
| `admin` | Staff permissions plus user and role management |

Public registration always creates `patient` accounts. Do not expose a public
setup route for admin creation.

## Admin Bootstrap

`python -m app.cli bootstrap-admin` is safe to run repeatedly:

- It exits successfully when bootstrap env vars are missing.
- It does nothing once an active admin already exists.
- It validates passwords with the same rules as the API.
- It writes an audit record with `actor_email="bootstrap"`.

Emergency CLI helpers:

```bash
uv run python -m app.cli create-user --email staff@clinic.com --password 'Str0ngPassw0rd' --name 'Clinic Staff' --role staff
uv run python -m app.cli set-role --email someone@clinic.com --role staff
```

## Memory Endpoints

Memory controls are scoped to the signed-in user:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/memories/` | List active memories for the signed-in user |
| `DELETE` | `/api/memories/{memory_id}` | Soft-delete one owned memory |
| `DELETE` | `/api/memories/` | Clear all active owned memories |

## Database Notes

Schema changes are managed by Alembic.

For old databases created before Alembic, stamp the baseline once:

```bash
uv run alembic stamp 0001_initial
uv run alembic upgrade head
```

`0002_production_hardening` is defensive and checks the schema before adding
objects, so it can run against partially migrated development databases.

## Docker Notes

The backend Dockerfile is compatible with Docker's classic builder. It does not
require BuildKit cache mounts.

The backend compose file provides:

- `backend`: FastAPI on port `8000`
- `db`: PostgreSQL on host port `5434`
- `clinic_agent_postgres_data`: persistent database volume

Inside Compose, the backend uses `db:5432` for PostgreSQL, not `localhost`.

Useful commands:

```bash
docker compose up -d --build
docker compose logs -f backend
docker compose ps
docker compose down
```

## Health Checks

- `GET /health/live` checks process liveness only.
- `GET /health/ready` checks database readiness.

Use `GET`, not `HEAD`, for these endpoints.

## Production Notes

Before production:

- Set `ENVIRONMENT=production`.
- Use a strong `JWT_SECRET_KEY` of at least 32 characters.
- Set explicit `ALLOWED_ORIGINS`.
- Set explicit `TRUSTED_HOSTS`.
- Set `ENABLE_DOCS=false` unless public API docs are intended.
- Use a production secret manager for credentials.
- Run Alembic migrations instead of relying on startup table creation.
- Terminate TLS at a reverse proxy and forward `X-Forwarded-*` headers.
- Set `LOG_JSON=true` if logs are collected by a structured logging system.

Known limitations:

- Rate limiting is process-local; use Redis before running multiple replicas.
- Appointment email confirmation currently runs as a background task; use an
  outbox or queue for higher-volume production delivery.
- FAISS index files are generated from `data/` at runtime and are not copied into
  the Docker image.
