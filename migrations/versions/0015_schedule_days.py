"""Add working days to doctor schedules.

``doctor_schedule.working_days`` stores a comma-separated subset of the weekday
names; a ``NULL`` value keeps the pre-existing "works every day" behaviour.

Revision ID: 0015_schedule_days
Revises: 0014_profile_contact_details
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_schedule_days"
down_revision: str | None = "0014_profile_contact_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if not _has_column("doctor_schedule", "working_days"):
        op.add_column("doctor_schedule", sa.Column("working_days", sa.String(), nullable=True))


def downgrade() -> None:
    if _has_column("doctor_schedule", "working_days"):
        op.drop_column("doctor_schedule", "working_days")
