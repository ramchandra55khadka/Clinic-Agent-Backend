"""Convert long-term memory to slot-based preferences.

Revision ID: 0012_slot_based_memory
Revises: 0011_merge_user_auth
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_slot_based_memory"
down_revision: str | None = "0011_merge_user_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def _constraints(table: str) -> set[str]:
    return {constraint["name"] for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table)}


def upgrade() -> None:
    tables = _tables()
    if "user_profile" in tables and "memory_enabled" not in _columns("user_profile"):
        op.add_column(
            "user_profile",
            sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )

    if "long_term_memory" not in tables:
        return

    cols = _columns("long_term_memory")
    if "key" not in cols:
        op.add_column("long_term_memory", sa.Column("key", sa.String(length=50), nullable=True))
    if "value" not in cols:
        op.add_column("long_term_memory", sa.Column("value", sa.String(length=200), nullable=True))
    if "source_conversation_id" not in cols:
        op.add_column("long_term_memory", sa.Column("source_conversation_id", sa.String(length=36), nullable=True))
    if "updated_at" not in cols:
        op.add_column(
            "long_term_memory",
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "last_used_at" not in cols:
        op.add_column("long_term_memory", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))

    bind = op.get_bind()
    cols = _columns("long_term_memory")
    if {"memory_key", "content", "key", "value"} <= cols:
        rows = bind.execute(sa.text("SELECT id, memory_key, content FROM long_term_memory")).mappings()
        for row in rows:
            content = " ".join((row["content"] or "").strip().strip(".").split())
            lowered = content.lower()
            key = None
            value = None
            if "morning" in lowered:
                key, value = "preferred_time", "Morning appointments"
            elif "afternoon" in lowered:
                key, value = "preferred_time", "Afternoon appointments"
            elif "evening" in lowered:
                key, value = "preferred_time", "Evening appointments"
            elif "email" in lowered:
                key, value = "contact_preference", "Email"
            elif "phone" in lowered or "sms" in lowered or "text" in lowered:
                key, value = "contact_preference", "Phone or SMS"
            else:
                key, value = "contact_preference", content[:200] or row["memory_key"][:200]

            bind.execute(
                sa.text("UPDATE long_term_memory SET key = :key, value = :value WHERE id = :id"),
                {"key": key, "value": value, "id": row["id"]},
            )

    # Remove duplicate slots before enforcing the unique user/key invariant.
    if {"user_id", "key", "updated_at"} <= _columns("long_term_memory"):
        duplicates = bind.execute(
            sa.text(
                """
                SELECT user_id, key, MIN(id) AS keep_id
                FROM long_term_memory
                GROUP BY user_id, key
                HAVING COUNT(*) > 1
                """
            )
        ).mappings()
        for duplicate in duplicates:
            bind.execute(
                sa.text(
                    "DELETE FROM long_term_memory WHERE user_id = :user_id AND key = :key AND id != :keep_id"
                ),
                {
                    "user_id": duplicate["user_id"],
                    "key": duplicate["key"],
                    "keep_id": duplicate["keep_id"],
                },
            )

    with op.batch_alter_table("long_term_memory") as batch:
        if "ix_long_term_memory_user_deleted" in _indexes("long_term_memory"):
            batch.drop_index("ix_long_term_memory_user_deleted")
        for old in ("kind", "memory_key", "content", "source", "confidence", "embedding_json", "deleted_at"):
            if old in _columns("long_term_memory"):
                batch.drop_column(old)

    with op.batch_alter_table("long_term_memory") as batch:
        batch.alter_column("key", existing_type=sa.String(length=50), nullable=False)
        batch.alter_column("value", existing_type=sa.String(length=200), nullable=False)
        if not any(
            fk.get("referred_table") == "conversation"
            for fk in sa.inspect(op.get_bind()).get_foreign_keys("long_term_memory")
        ):
            batch.create_foreign_key(
                "long_term_memory_source_conversation_id_fkey",
                "conversation",
                ["source_conversation_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "uq_memory_user_key" not in _constraints("long_term_memory"):
            batch.create_unique_constraint("uq_memory_user_key", ["user_id", "key"])


def downgrade() -> None:
    if "long_term_memory" in _tables():
        with op.batch_alter_table("long_term_memory") as batch:
            if "uq_memory_user_key" in _constraints("long_term_memory"):
                batch.drop_constraint("uq_memory_user_key", type_="unique")
            columns = _columns("long_term_memory")
            if "kind" not in columns:
                batch.add_column(sa.Column("kind", sa.String(length=32), nullable=False, server_default="preference"))
            if "memory_key" not in columns:
                batch.add_column(sa.Column("memory_key", sa.String(length=180), nullable=False, server_default=""))
            if "content" not in columns:
                batch.add_column(sa.Column("content", sa.Text(), nullable=False, server_default=""))
            if "source" not in columns:
                batch.add_column(sa.Column("source", sa.String(length=32), nullable=False, server_default="chat"))
            if "confidence" not in columns:
                batch.add_column(sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"))
            if "embedding_json" not in columns:
                batch.add_column(sa.Column("embedding_json", sa.Text(), nullable=True))
            if "deleted_at" not in columns:
                batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    if "user_profile" in _tables() and "memory_enabled" in _columns("user_profile"):
        op.drop_column("user_profile", "memory_enabled")
