"""Convert existing integer user identifiers to string IDs.

Revision ID: 0004_user_id_string_columns
Revises: 0003_user_uuid_primary_keys
Create Date: 2026-09-18

Fresh databases already create user identifiers as String(36). This migration is
for databases that were stamped/applied before the UUID primary-key change and
therefore still have integer user_account.id/user_id columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_id_string_columns"
down_revision: str | None = "0003_user_uuid_primary_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


USER_FKS = (
    ("user_auth", "user_auth_user_id_fkey", "user_id", "CASCADE"),
    ("refresh_token", "refresh_token_user_id_fkey", "user_id", "CASCADE"),
    ("audit_log", "audit_log_actor_id_fkey", "actor_id", "SET NULL"),
)


def _column_type(table_name: str, column_name: str):
    inspector = sa.inspect(op.get_bind())
    for column in inspector.get_columns(table_name):
        if column["name"] == column_name:
            return column["type"]
    return None


def _is_integer_user_id_schema() -> bool:
    return isinstance(_column_type("user_account", "id"), sa.Integer)


def _drop_constraint_if_exists(table_name: str, constraint_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    names = {fk["name"] for fk in inspector.get_foreign_keys(table_name)}
    names.add(inspector.get_pk_constraint(table_name).get("name"))
    if constraint_name in names:
        op.drop_constraint(constraint_name, table_name, type_="foreignkey" if constraint_name.endswith("fkey") else "primary")


def upgrade() -> None:
    if not _is_integer_user_id_schema():
        return

    for table_name, constraint_name, _column_name, _ondelete in USER_FKS:
        _drop_constraint_if_exists(table_name, constraint_name)

    pk_name = sa.inspect(op.get_bind()).get_pk_constraint("user_account").get("name")
    if pk_name:
        op.drop_constraint(pk_name, "user_account", type_="primary")

    op.alter_column(
        "user_account",
        "id",
        existing_type=sa.Integer(),
        type_=sa.String(length=36),
        postgresql_using="id::varchar",
        existing_nullable=False,
    )
    op.alter_column(
        "user_auth",
        "user_id",
        existing_type=sa.Integer(),
        type_=sa.String(length=36),
        postgresql_using="user_id::varchar",
        existing_nullable=False,
    )
    op.alter_column(
        "refresh_token",
        "user_id",
        existing_type=sa.Integer(),
        type_=sa.String(length=36),
        postgresql_using="user_id::varchar",
        existing_nullable=False,
    )
    op.alter_column(
        "audit_log",
        "actor_id",
        existing_type=sa.Integer(),
        type_=sa.String(length=36),
        postgresql_using="actor_id::varchar",
        existing_nullable=True,
    )

    op.create_primary_key("user_account_pkey", "user_account", ["id"])
    for table_name, constraint_name, column_name, ondelete in USER_FKS:
        op.create_foreign_key(
            constraint_name,
            table_name,
            "user_account",
            [column_name],
            ["id"],
            ondelete=ondelete,
        )


def downgrade() -> None:
    # UUID/string user IDs are the forward schema standard. Downgrading could
    # destroy accounts created with non-integer UUID identifiers.
    pass
