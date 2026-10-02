"""Add optional photo to doctor schedules.

Revision ID: 0006_doctor_photo_url
Revises: 0005_profile_photo_url
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_doctor_photo_url"
down_revision: str | None = "0005_profile_photo_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if not _has_column("doctor_schedule", "photo_url"):
        op.add_column("doctor_schedule", sa.Column("photo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("doctor_schedule", "photo_url"):
        op.drop_column("doctor_schedule", "photo_url")
