"""Add conversations and long-term memories.

Revision ID: 0007_conversations_memory
Revises: 0006_doctor_photo_url
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_conversations_memory"
down_revision: str | None = "0006_doctor_photo_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        available = bind.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        ).scalar()
        if available:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    if not _has_table("conversation"):
        op.create_table(
            "conversation",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("session_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_conversation_id", "conversation", ["id"])
        op.create_index("ix_conversation_session_id", "conversation", ["session_id"], unique=True)
        op.create_index("ix_conversation_user_id", "conversation", ["user_id"])

    if not _has_table("conversation_message"):
        op.create_table(
            "conversation_message",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("intent", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_conversation_message_id", "conversation_message", ["id"])
        op.create_index("ix_conversation_message_conversation_id", "conversation_message", ["conversation_id"])
        op.create_index("ix_conversation_message_user_id", "conversation_message", ["user_id"])

    if not _has_table("long_term_memory"):
        op.create_table(
            "long_term_memory",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("memory_key", sa.String(length=180), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("embedding_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_long_term_memory_id", "long_term_memory", ["id"])
        op.create_index("ix_long_term_memory_user_id", "long_term_memory", ["user_id"])
        op.create_index("ix_long_term_memory_user_deleted", "long_term_memory", ["user_id", "deleted_at"])


def downgrade() -> None:
    if _has_table("long_term_memory"):
        op.drop_table("long_term_memory")
    if _has_table("conversation_message"):
        op.drop_table("conversation_message")
    if _has_table("conversation"):
        op.drop_table("conversation")
