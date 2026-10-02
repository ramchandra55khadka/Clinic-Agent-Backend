"""Production hardening: lockout counters, refresh tokens and the audit log.

Revision ID: 0002_production_hardening
Revises: 0001_initial
Create Date: 2026-09-18

Every step is guarded by an introspection check so the revision can also be
applied to databases that were created with ``create_all()`` and already contain
some (or all) of these objects.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_production_hardening"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _table_names()

    if "user_auth" in tables:
        columns = _column_names("user_auth")
        if "password_changed_at" not in columns:
            op.add_column("user_auth", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
        if "failed_login_attempts" not in columns:
            op.add_column(
                "user_auth",
                sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
            )
        if "locked_until" not in columns:
            op.add_column("user_auth", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))

    if "refresh_token" not in tables:
        op.create_table(
            "refresh_token",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("user_account.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replaced_by_id", sa.Integer(), sa.ForeignKey("refresh_token.id"), nullable=True),
            sa.Column("user_agent", sa.String(), nullable=True),
            sa.Column("client_ip", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_refresh_token_id", "refresh_token", ["id"])
        op.create_index("ix_refresh_token_user_id", "refresh_token", ["user_id"])
        op.create_index("ix_refresh_token_token_hash", "refresh_token", ["token_hash"], unique=True)

    if "audit_log" not in tables:
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "actor_id",
                sa.String(length=36),
                sa.ForeignKey("user_account.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("actor_email", sa.String(), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("entity", sa.String(length=64), nullable=True),
            sa.Column("entity_id", sa.String(), nullable=True),
            sa.Column("client_ip", sa.String(), nullable=True),
            sa.Column("user_agent", sa.String(), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_audit_log_id", "audit_log", ["id"])
        op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
        op.create_index("ix_audit_log_action", "audit_log", ["action"])
        op.create_index("ix_audit_log_action_created", "audit_log", ["action", "created_at"])


def downgrade() -> None:
    tables = _table_names()

    if "audit_log" in tables:
        op.drop_table("audit_log")
    if "refresh_token" in tables:
        op.drop_table("refresh_token")
    if "user_auth" in tables:
        for column in ("locked_until", "failed_login_attempts", "password_changed_at"):
            if column in _column_names("user_auth"):
                op.drop_column("user_auth", column)