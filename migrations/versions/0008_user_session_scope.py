"""Scope conversation sessions per user.

Revision ID: 0008_user_session_scope
Revises: 0007_conversations_memory
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_user_session_scope"
down_revision: str | None = "0007_conversations_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def _has_constraint(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    )


def upgrade() -> None:
    if not _has_table("conversation"):
        return

    if _has_index("conversation", "ix_conversation_session_id"):
        op.drop_index("ix_conversation_session_id", table_name="conversation")
    op.create_index("ix_conversation_session_id", "conversation", ["session_id"], unique=False)

    if not _has_constraint("conversation", "uq_conversation_user_session"):
        with op.batch_alter_table("conversation") as batch:
            batch.create_unique_constraint(
                "uq_conversation_user_session",
                ["user_id", "session_id"],
            )


def downgrade() -> None:
    if not _has_table("conversation"):
        return

    if _has_constraint("conversation", "uq_conversation_user_session"):
        with op.batch_alter_table("conversation") as batch:
            batch.drop_constraint("uq_conversation_user_session", type_="unique")
    if _has_index("conversation", "ix_conversation_session_id"):
        op.drop_index("ix_conversation_session_id", table_name="conversation")
    op.create_index("ix_conversation_session_id", "conversation", ["session_id"], unique=True)
