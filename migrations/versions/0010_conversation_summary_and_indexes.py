"""Add summary to conversation and indexes for messages

Revision ID: 0010_conv_summary_and_indexes
Revises: 0009_normalized_profiles
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# NOTE: kept to <=32 chars — ``alembic_version.version_num`` is VARCHAR(32), so a
# longer id cannot be written back after the upgrade runs.
revision: str = "0010_conv_summary_and_indexes"
down_revision: str | None = "0009_normalized_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    columns = [c["name"] for c in inspector.get_columns(table_name)]
    return column_name in columns


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    indexes = [i["name"] for i in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    if _has_table("conversation") and not _has_column("conversation", "summary"):
        op.add_column(
            "conversation",
            sa.Column("summary", sa.Text(), nullable=True),
        )
    if _has_table("conversation") and not _has_column("conversation", "title"):
        op.add_column(
            "conversation",
            sa.Column("title", sa.String(length=200), nullable=True),
        )
    if _has_table("conversation") and not _has_column("conversation", "message_count"):
        op.add_column(
            "conversation",
            sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        )

    if _has_table("conversation_message") and not _has_index(
        "conversation_message", "ix_conversation_message_conversation_created_at"
    ):
        op.create_index(
            "ix_conversation_message_conversation_created_at",
            "conversation_message",
            ["conversation_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    if _has_table("conversation_message") and _has_index(
        "conversation_message", "ix_conversation_message_conversation_created_at"
    ):
        op.drop_index(
            "ix_conversation_message_conversation_created_at",
            table_name="conversation_message",
        )
    if _has_table("conversation") and _has_column("conversation", "message_count"):
        op.drop_column("conversation", "message_count")
    if _has_table("conversation") and _has_column("conversation", "title"):
        op.drop_column("conversation", "title")
    if _has_table("conversation") and _has_column("conversation", "summary"):
        op.drop_column("conversation", "summary")
