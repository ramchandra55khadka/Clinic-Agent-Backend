"""Initial schema: doctor schedules, appointments, accounts and credentials.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-18

Databases created earlier by ``Base.metadata.create_all()`` already contain these
tables and must be stamped rather than upgraded into this revision:

    alembic stamp 0001_initial && alembic upgrade head
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doctor_schedule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doctor_name", sa.String(), nullable=False),
        sa.Column("specialization", sa.String(), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("break_start", sa.Time(), nullable=True),
        sa.Column("break_end", sa.Time(), nullable=True),
        sa.Column("leave_date", sa.Date(), nullable=True),
        sa.Column("slot_duration", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_doctor_schedule_id", "doctor_schedule", ["id"])

    op.create_table(
        "user_account",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_account_id", "user_account", ["id"])
    op.create_index("ix_user_account_email", "user_account", ["email"], unique=True)

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doctor_id", sa.Integer(), sa.ForeignKey("doctor_schedule.id"), nullable=False),
        sa.Column("patient_name", sa.String(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("sex", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("time", sa.Time(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("confirmation_email_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("doctor_id", "date", "time", name="uq_appointment_doctor_slot"),
    )
    op.create_index("ix_appointments_id", "appointments", ["id"])
    op.create_index("ix_appointments_doctor_id", "appointments", ["doctor_id"])

    op.create_table(
        "user_auth",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_auth_id", "user_auth", ["id"])
    op.create_index("ix_user_auth_user_id", "user_auth", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_table("user_auth")
    op.drop_table("appointments")
    op.drop_table("user_account")
    op.drop_table("doctor_schedule")