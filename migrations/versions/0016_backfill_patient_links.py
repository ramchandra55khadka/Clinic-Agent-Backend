"""Link chat-booked appointments to the booking account's patient row.

Bookings made through the chat assistant were only linked to a patient when the
email typed during the conversation happened to match an account. Tracking is
account-based now, so this backfills ``appointments.patient_id`` for rows whose
chat confirmation message proves which account made the booking: the message
carries the slot's date/time and belongs to a user, and it was written within
a minute of the row's creation.

Revision ID: 0016_backfill_patient_links
Revises: 0015_schedule_days
Create Date: 2026-10-05
"""

import re
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

# NOTE: kept to <=32 chars — ``alembic_version.version_num`` is VARCHAR(32), so a
# longer id cannot be written back after the upgrade runs.
revision: str = "0016_backfill_patient_links"
down_revision: str | None = "0015_schedule_days"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# "Your appointment is confirmed for 2026-10-07 at 12:00:00. …"
_CONFIRMATION = re.compile(r"for (\d{4}-\d{2}-\d{2}) at (\d{2}:\d{2}:\d{2})")


def _moment(value) -> datetime | None:
    """A naive datetime from either a real column (Postgres) or the stored
    string (SQLite); tz info is dropped so representations stay comparable."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def upgrade() -> None:
    bind = op.get_bind()
    messages = bind.execute(
        sa.text(
            "select user_id, content, created_at from conversation_message "
            "where role = 'assistant' and content like 'Your appointment is confirmed for%'"
        )
    ).fetchall()
    orphans = [
        {"id": row.id, "date": row.date, "time": row.time, "created_at": row.created_at}
        for row in bind.execute(
            sa.text("select id, date, time, created_at from appointments where patient_id is null")
        ).fetchall()
    ]

    for message in messages:
        match = _CONFIRMATION.search(message.content or "")
        if match is None:
            continue
        wanted_date, wanted_time = match.group(1), match.group(2)
        candidates = [
            appointment
            for appointment in orphans
            if str(appointment["date"])[:10] == wanted_date
            and str(appointment["time"])[:8] == wanted_time
        ]
        if not candidates:
            continue
        if len(candidates) > 1:
            # Same slot can only be booked once per doctor; several candidates
            # mean different doctors — use the write timestamp to disambiguate.
            message_at = _moment(message.created_at)
            nearby = [
                appointment
                for appointment in candidates
                if message_at is not None
                and _moment(appointment["created_at"]) is not None
                and abs((_moment(appointment["created_at"]) - message_at).total_seconds()) <= 60
            ]
            if len(nearby) != 1:
                # Genuinely ambiguous — leave those rows to the email fallback.
                continue
            candidates = nearby
        appointment = candidates[0]

        patient = bind.execute(
            sa.text(
                "select p.id from patient p "
                "join user_profile up on p.profile_id = up.id "
                "where up.user_id = :user_id"
            ),
            {"user_id": message.user_id},
        ).first()
        if patient is None:
            # The account has no patient row; the email fallback still covers it.
            continue

        bind.execute(
            sa.text(
                "update appointments set patient_id = :patient_id "
                "where id = :id and patient_id is null"
            ),
            {"patient_id": patient[0], "id": appointment["id"]},
        )
        orphans.remove(appointment)


def downgrade() -> None:
    # Data-only backfill: nothing structural to reverse.
    pass