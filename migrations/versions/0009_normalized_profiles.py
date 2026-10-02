"""Normalize accounts into user_profile + doctor/patient.

Revision ID: 0009_normalized_profiles
Revises: 8f448ec0e4ee
Create Date: 2026-10-01

This revision splits the denormalized account/doctor data into dedicated tables:

* ``user_profile`` — name/phone/photo, 1:1 with ``user_account`` (nullable FK so a
  doctor entered by staff can exist without a login account).
* ``doctor`` / ``patient`` — 1:1 with ``user_profile``; ``doctor_education`` holds
  a doctor's education history.
* ``doctor_schedule`` now points at ``doctor.id`` (its ``doctor_name`` /
  ``specialization`` / ``photo_url`` columns are dropped).
* ``appointments`` gains ``patient_id``; its ``doctor_id`` is remapped from the
  old schedule id to the new doctor id.

Everything is guarded by introspection so it is safe on databases that only
partially match the pre-0009 schema, and a data-backfill migrates existing rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_normalized_profiles"
down_revision: str | None = "8f448ec0e4ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    return any(item["name"] == index for item in sa.inspect(op.get_bind()).get_indexes(table))


def _create_profile_and_specialisation_tables(tables: set[str]) -> None:
    if "user_profile" not in tables:
        op.create_table(
            "user_profile",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("user_account.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("full_name", sa.String(), nullable=False),
            sa.Column("phone", sa.String(), nullable=True),
            sa.Column("photo_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_user_profile_id", "user_profile", ["id"])
        op.create_index("ix_user_profile_user_id", "user_profile", ["user_id"], unique=True)

    if "doctor" not in tables:
        op.create_table(
            "doctor",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "profile_id",
                sa.Integer(),
                sa.ForeignKey("user_profile.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("license_number", sa.String(length=64), nullable=True),
            sa.Column("specialization", sa.String(), nullable=True),
            sa.Column("qualification", sa.String(), nullable=True),
            sa.Column("experience_years", sa.Integer(), nullable=True),
            sa.Column("bio", sa.Text(), nullable=True),
            sa.Column("consultation_fee", sa.Float(), nullable=True),
            sa.Column("consultation_duration", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_doctor_id", "doctor", ["id"])
        op.create_index("ix_doctor_profile_id", "doctor", ["profile_id"], unique=True)

    if "doctor_education" not in tables:
        op.create_table(
            "doctor_education",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "doctor_id",
                sa.Integer(),
                sa.ForeignKey("doctor.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("degree", sa.String(length=150), nullable=False),
            sa.Column("institution", sa.String(length=200), nullable=False),
            sa.Column("field_of_study", sa.String(length=150), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_doctor_education_doctor_id", "doctor_education", ["doctor_id"])

    if "patient" not in tables:
        op.create_table(
            "patient",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "profile_id",
                sa.Integer(),
                sa.ForeignKey("user_profile.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("date_of_birth", sa.Date(), nullable=True),
            sa.Column("gender", sa.String(), nullable=True),
            sa.Column("blood_group", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_patient_id", "patient", ["id"])
        op.create_index("ix_patient_profile_id", "patient", ["profile_id"], unique=True)


def _backfill_user_profiles() -> None:
    """Create a ``user_profile`` (and patient row) for every existing account."""
    if "full_name" not in _column_names("user_account"):
        return

    bind = op.get_bind()
    user_account = sa.table(
        "user_account",
        sa.column("id", sa.String),
        sa.column("full_name", sa.String),
        sa.column("phone", sa.String),
        sa.column("profile_photo_url", sa.Text),
        sa.column("role", sa.String),
    )
    user_profile = sa.table(
        "user_profile",
        sa.column("id", sa.Integer),
        sa.column("user_id", sa.String),
        sa.column("full_name", sa.String),
        sa.column("phone", sa.String),
        sa.column("photo_url", sa.Text),
    )
    patient = sa.table("patient", sa.column("id", sa.Integer), sa.column("profile_id", sa.Integer))

    rows = bind.execute(
        sa.select(
            user_account.c.id,
            user_account.c.full_name,
            user_account.c.phone,
            user_account.c.profile_photo_url,
            user_account.c.role,
        )
    ).fetchall()

    for row in rows:
        already = bind.execute(sa.select(user_profile.c.id).where(user_profile.c.user_id == row.id)).first()
        if already:
            continue
        bind.execute(
            user_profile.insert().values(
                user_id=row.id,
                full_name=row.full_name or row.id,
                phone=row.phone,
                photo_url=row.profile_photo_url,
            )
        )
        profile_id = bind.execute(sa.select(user_profile.c.id).where(user_profile.c.user_id == row.id)).scalar()
        if (row.role or "").strip().lower() == "patient":
            bind.execute(patient.insert().values(profile_id=profile_id))


def _backfill_doctors() -> dict[int, int]:
    """Create a ``doctor`` per existing schedule; returns old schedule id -> doctor id."""
    if "doctor_name" not in _column_names("doctor_schedule"):
        return {}

    bind = op.get_bind()
    doctor_schedule = sa.table(
        "doctor_schedule",
        sa.column("id", sa.Integer),
        sa.column("doctor_name", sa.String),
        sa.column("specialization", sa.String),
        sa.column("photo_url", sa.Text),
        sa.column("slot_duration", sa.Integer),
        sa.column("doctor_id", sa.Integer),
    )
    user_profile = sa.table(
        "user_profile",
        sa.column("id", sa.Integer),
        sa.column("user_id", sa.String),
        sa.column("full_name", sa.String),
        sa.column("phone", sa.String),
        sa.column("photo_url", sa.Text),
    )
    doctor = sa.table(
        "doctor",
        sa.column("id", sa.Integer),
        sa.column("profile_id", sa.Integer),
        sa.column("specialization", sa.String),
        sa.column("consultation_duration", sa.Integer),
        # NOT NULL with no DB default when the table was created by
        # Base.metadata.create_all() (the model's default=False is Python-side
        # only), so the backfill must set it explicitly.
        sa.column("is_verified", sa.Boolean),
    )

    mapping: dict[int, int] = {}
    rows = bind.execute(
        sa.select(
            doctor_schedule.c.id,
            doctor_schedule.c.doctor_name,
            doctor_schedule.c.specialization,
            doctor_schedule.c.photo_url,
            doctor_schedule.c.slot_duration,
        )
    ).fetchall()

    for row in rows:
        full_name = row.doctor_name or f"Doctor {row.id}"
        bind.execute(
            user_profile.insert().values(user_id=None, full_name=full_name, phone=None, photo_url=row.photo_url)
        )
        profile_id = bind.execute(
            sa.select(user_profile.c.id)
            .where(user_profile.c.user_id.is_(None), user_profile.c.full_name == full_name)
            .order_by(user_profile.c.id.desc())
        ).scalar()
        bind.execute(
            doctor.insert().values(
                profile_id=profile_id,
                specialization=row.specialization,
                consultation_duration=row.slot_duration or 30,
                is_verified=False,
            )
        )
        doctor_id = bind.execute(sa.select(doctor.c.id).where(doctor.c.profile_id == profile_id)).scalar()
        bind.execute(sa.update(doctor_schedule).where(doctor_schedule.c.id == row.id).values(doctor_id=doctor_id))
        mapping[row.id] = doctor_id

    return mapping


def upgrade() -> None:
    tables = _table_names()
    _create_profile_and_specialisation_tables(tables)

    # Add doctor_schedule.doctor_id first so the backfill below can populate it.
    if "doctor_id" not in _column_names("doctor_schedule"):
        op.add_column("doctor_schedule", sa.Column("doctor_id", sa.Integer(), nullable=True))
    if not _has_index("doctor_schedule", "ix_doctor_schedule_doctor_id"):
        op.create_index("ix_doctor_schedule_doctor_id", "doctor_schedule", ["doctor_id"])

    _backfill_user_profiles()
    schedule_to_doctor = _backfill_doctors()

    # ---- finalize doctor_schedule: NOT NULL + FK, drop the legacy columns ----
    if "doctor_name" in _column_names("doctor_schedule"):
        with op.batch_alter_table("doctor_schedule") as batch:
            batch.alter_column("doctor_id", existing_type=sa.Integer(), nullable=False)
            if not any(
                fk.get("referred_table") == "doctor"
                for fk in sa.inspect(op.get_bind()).get_foreign_keys("doctor_schedule")
            ):
                batch.create_foreign_key(
                    "doctor_schedule_doctor_id_fkey",
                    "doctor",
                    ["doctor_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            for column in ("doctor_name", "specialization", "photo_url"):
                if column in _column_names("doctor_schedule"):
                    batch.drop_column(column)

    # ---- appointments.patient_id + remap doctor ids (single statement) ----
    if "patient_id" not in _column_names("appointments"):
        with op.batch_alter_table("appointments") as batch:
            batch.add_column(sa.Column("patient_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "appointments_patient_id_fkey",
                "patient",
                ["patient_id"],
                ["id"],
                ondelete="SET NULL",
            )
    if not _has_index("appointments", "ix_appointments_patient_id"):
        op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"])

    # Link existing appointments to a patient by matching the booking email.
    bind = op.get_bind()
    appointments = sa.table(
        "appointments",
        sa.column("id", sa.Integer),
        sa.column("email", sa.String),
        sa.column("patient_id", sa.Integer),
    )
    patient = sa.table("patient", sa.column("id", sa.Integer), sa.column("profile_id", sa.Integer))
    user_profile = sa.table("user_profile", sa.column("id", sa.Integer), sa.column("user_id", sa.String))
    user_account = sa.table("user_account", sa.column("id", sa.String), sa.column("email", sa.String))
    linked_patient = (
        patient.join(user_profile, patient.c.profile_id == user_profile.c.id)
        .join(user_account, user_profile.c.user_id == user_account.c.id)
    )
    for row in bind.execute(sa.select(appointments.c.id, appointments.c.email)).fetchall():
        if not row.email:
            continue
        patient_id = bind.execute(
            sa.select(patient.c.id)
            .select_from(linked_patient)
            .where(sa.func.lower(user_account.c.email) == row.email.strip().lower())
        ).scalar()
        if patient_id:
            bind.execute(sa.update(appointments).where(appointments.c.id == row.id).values(patient_id=patient_id))

    # Repoint appointments.doctor_id from doctor_schedule.id to doctor.id.
    # The old FK must be dropped *before* the values are rewritten: the new
    # doctor ids do not exist in doctor_schedule and the old schedule ids do not
    # exist in doctor, so no FK can be attached while the swap happens.
    for fk in sa.inspect(bind).get_foreign_keys("appointments"):
        if fk.get("referred_table") == "doctor_schedule" and fk.get("name"):
            with op.batch_alter_table("appointments") as batch:
                batch.drop_constraint(fk["name"], type_="foreignkey")
            break

    if schedule_to_doctor:
        appointments = sa.table(
            "appointments",
            sa.column("id", sa.Integer),
            sa.column("doctor_id", sa.Integer),
        )
        remap = sa.case(schedule_to_doctor, value=appointments.c.doctor_id, else_=appointments.c.doctor_id)
        bind.execute(sa.update(appointments).values(doctor_id=remap))

    if not any(fk.get("referred_table") == "doctor" for fk in sa.inspect(bind).get_foreign_keys("appointments")):
        with op.batch_alter_table("appointments") as batch:
            batch.create_foreign_key("appointments_doctor_id_fkey", "doctor", ["doctor_id"], ["id"])

    # ---- user_account: drop the moved profile columns ----
    account_columns = _column_names("user_account")
    with op.batch_alter_table("user_account") as batch:
        for column in ("full_name", "phone", "profile_photo_url"):
            if column in account_columns:
                batch.drop_column(column)


def downgrade() -> None:
    bind = op.get_bind()

    # Restore the denormalized account columns and backfill from profiles.
    if "full_name" not in _column_names("user_account"):
        op.add_column("user_account", sa.Column("full_name", sa.String(), nullable=True))
    if "phone" not in _column_names("user_account"):
        op.add_column("user_account", sa.Column("phone", sa.String(), nullable=True))
    if "profile_photo_url" not in _column_names("user_account"):
        op.add_column("user_account", sa.Column("profile_photo_url", sa.Text(), nullable=True))

    user_account = sa.table(
        "user_account",
        sa.column("id", sa.String),
        sa.column("full_name", sa.String),
        sa.column("phone", sa.String),
        sa.column("profile_photo_url", sa.Text),
    )
    user_profile = sa.table(
        "user_profile",
        sa.column("id", sa.Integer),
        sa.column("user_id", sa.String),
        sa.column("full_name", sa.String),
        sa.column("phone", sa.String),
        sa.column("photo_url", sa.Text),
    )
    for profile in bind.execute(
        sa.select(user_profile.c.user_id, user_profile.c.full_name, user_profile.c.phone, user_profile.c.photo_url)
    ).fetchall():
        if profile.user_id is None:
            continue
        bind.execute(
            sa.update(user_account)
            .where(user_account.c.id == profile.user_id)
            .values(full_name=profile.full_name, phone=profile.phone, profile_photo_url=profile.photo_url)
        )

    # Restore doctor_schedule legacy columns from doctor/profile.
    if "doctor_name" not in _column_names("doctor_schedule"):
        op.add_column("doctor_schedule", sa.Column("doctor_name", sa.String(), nullable=True))
        op.add_column("doctor_schedule", sa.Column("specialization", sa.String(), nullable=True))
        op.add_column("doctor_schedule", sa.Column("photo_url", sa.Text(), nullable=True))

    if "doctor_id" in _column_names("doctor_schedule"):
        doctor = sa.table(
            "doctor",
            sa.column("id", sa.Integer),
            sa.column("profile_id", sa.Integer),
            sa.column("specialization", sa.String),
        )
        doctor_schedule = sa.table(
            "doctor_schedule",
            sa.column("id", sa.Integer),
            sa.column("doctor_id", sa.Integer),
            sa.column("doctor_name", sa.String),
            sa.column("specialization", sa.String),
            sa.column("photo_url", sa.Text),
        )
        for row in bind.execute(
            sa.select(
                doctor_schedule.c.id,
                doctor.c.specialization,
                user_profile.c.full_name,
                user_profile.c.photo_url,
            )
            .select_from(
                doctor_schedule.join(doctor, doctor_schedule.c.doctor_id == doctor.c.id).join(
                    user_profile, doctor.c.profile_id == user_profile.c.id
                )
            )
        ).fetchall():
            bind.execute(
                sa.update(doctor_schedule)
                .where(doctor_schedule.c.id == row.id)
                .values(doctor_name=row.full_name, specialization=row.specialization, photo_url=row.photo_url)
            )

    if _has_index("appointments", "ix_appointments_patient_id"):
        op.drop_index("ix_appointments_patient_id", table_name="appointments")
    if "patient_id" in _column_names("appointments"):
        op.drop_column("appointments", "patient_id")

    # Repoint appointments.doctor_id back to doctor_schedule and remap the ids.
    if "doctor_id" in _column_names("doctor_schedule"):
        doctor_schedule = sa.table(
            "doctor_schedule",
            sa.column("id", sa.Integer),
            sa.column("doctor_id", sa.Integer),
        )
        appointment = sa.table(
            "appointments",
            sa.column("id", sa.Integer),
            sa.column("doctor_id", sa.Integer),
        )
        mapping = {
            row.doctor_id: row.id
            for row in bind.execute(sa.select(doctor_schedule.c.id, doctor_schedule.c.doctor_id)).fetchall()
            if row.doctor_id is not None
        }
        if mapping:
            remap = sa.case(mapping, value=appointment.c.doctor_id, else_=appointment.c.doctor_id)
            bind.execute(sa.update(appointment).values(doctor_id=remap))
        for fk in sa.inspect(bind).get_foreign_keys("appointments"):
            if fk.get("referred_table") == "doctor" and fk.get("name"):
                op.drop_constraint(fk["name"], "appointments", type_="foreignkey")
                op.create_foreign_key(
                    "appointments_doctor_id_fkey", "appointments", "doctor_schedule", ["doctor_id"], ["id"]
                )
                break

    if _has_index("doctor_schedule", "ix_doctor_schedule_doctor_id"):
        op.drop_index("ix_doctor_schedule_doctor_id", table_name="doctor_schedule")
    if "doctor_id" in _column_names("doctor_schedule"):
        op.drop_column("doctor_schedule", "doctor_id")

    for table in ("doctor_education", "patient", "doctor", "user_profile"):
        if table in _table_names():
            op.drop_table(table)
