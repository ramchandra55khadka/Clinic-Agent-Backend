"""Fold user_auth into user_account.

Revision ID: 0011_merge_user_auth
Revises: 0010_conv_summary_and_indexes
Create Date: 2026-10-01

``user_auth`` was a strict 1:1 extension of ``user_account`` holding only the
password credential and the sign-in security state, so it is merged into
``user_account`` as five columns. ``password_hash`` stays nullable, preserving
the old behaviour where an account with no ``user_auth`` row could not sign in.

Every step is guarded by introspection, so the revision is safe on databases
that never had ``user_auth`` (or that already had some of the columns).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_merge_user_auth"
down_revision: str | None = "0010_conv_summary_and_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (column name, type, nullable, server default)
CREDENTIAL_COLUMNS = (
    ("password_hash", sa.String(), True, None),
    ("password_changed_at", sa.DateTime(timezone=True), True, None),
    ("last_login_at", sa.DateTime(timezone=True), True, None),
    ("failed_login_attempts", sa.Integer(), False, "0"),
    ("locked_until", sa.DateTime(timezone=True), True, None),
)

CREDENTIAL_NAMES = tuple(name for name, _, _, _ in CREDENTIAL_COLUMNS)


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()
    if "user_account" not in tables:
        return

    account_columns = _column_names("user_account")
    for name, type_, nullable, default in CREDENTIAL_COLUMNS:
        if name not in account_columns:
            op.add_column(
                "user_account",
                sa.Column(name, type_, nullable=nullable, server_default=default),
            )

    if "user_auth" not in tables:
        return

    source_columns = _column_names("user_auth")
    copied = [name for name in CREDENTIAL_NAMES if name in source_columns]
    if "user_id" not in source_columns or not copied:
        op.drop_table("user_auth")
        return

    source = sa.table(
        "user_auth",
        sa.column("user_id", sa.String()),
        *[sa.column(name) for name in copied],
    )
    target = sa.table(
        "user_account",
        sa.column("id", sa.String()),
        *[sa.column(name) for name in copied],
    )

    rows = bind.execute(sa.select(source)).mappings()
    for row in rows:
        bind.execute(
            sa.update(target)
            .where(target.c.id == row["user_id"])
            .values({name: row[name] for name in copied})
        )

    op.drop_table("user_auth")


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names()
    if "user_account" not in tables:
        return

    account_columns = _column_names("user_account")

    if "user_auth" not in tables:
        op.create_table(
            "user_auth",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("user_account.id"),
                nullable=False,
            ),
            sa.Column("password_hash", sa.String(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_user_auth_id", "user_auth", ["id"])
        op.create_index("ix_user_auth_user_id", "user_auth", ["user_id"], unique=True)

        present = [name for name in CREDENTIAL_NAMES if name in account_columns]
        account = sa.table(
            "user_account",
            sa.column("id", sa.String()),
            *[sa.column(name) for name in present],
        )
        auth = sa.table(
            "user_auth",
            sa.column("user_id", sa.String()),
            sa.column("password_hash", sa.String()),
            sa.column("password_changed_at", sa.DateTime(timezone=True)),
            sa.column("last_login_at", sa.DateTime(timezone=True)),
            sa.column("failed_login_attempts", sa.Integer()),
            sa.column("locked_until", sa.DateTime(timezone=True)),
        )
        for row in bind.execute(sa.select(account)).mappings():
            password = row["password_hash"] if "password_hash" in present else None
            if password is None:
                continue  # accounts without credentials never had a user_auth row
            bind.execute(
                sa.insert(auth).values(
                    user_id=row["id"],
                    password_hash=password,
                    password_changed_at=row["password_changed_at"] if "password_changed_at" in present else None,
                    last_login_at=row["last_login_at"] if "last_login_at" in present else None,
                    failed_login_attempts=(row["failed_login_attempts"] if "failed_login_attempts" in present else 0) or 0,
                    locked_until=row["locked_until"] if "locked_until" in present else None,
                )
            )

    account_columns = _column_names("user_account")
    for name in CREDENTIAL_NAMES:
        if name in account_columns:
            op.drop_column("user_account", name)
