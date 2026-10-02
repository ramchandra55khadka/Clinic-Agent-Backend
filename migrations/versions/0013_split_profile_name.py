"""Split user_profile.full_name into first_name and last_name.

Revision ID: 0013_split_profile_name
Revises: 0012_slot_based_memory
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_split_profile_name"
down_revision: str | None = "0012_slot_based_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _split(full_name: str | None) -> tuple[str, str | None]:
    """Mirror of ``app.models.user_profile.split_display_name``.

    The logic is duplicated here on purpose: migrations must keep working even
    after application code has moved on.
    """
    parts = (full_name or "").split()
    if not parts:
        return "", None
    if len(parts) == 1:
        return parts[0], None
    return " ".join(parts[:-1]), parts[-1]


def upgrade() -> None:
    """Add the split columns, backfill them from ``full_name``, then drop it.

    ``first_name`` is created NOT NULL with an empty default rather than being
    tightened afterwards: adding a NOT NULL column needs an immediate default on
    SQLite, and SQLite cannot ``ALTER COLUMN`` nullability without rebuilding
    the table.
    """
    columns = _columns("user_profile")

    if "first_name" not in columns:
        op.add_column(
            "user_profile",
            sa.Column("first_name", sa.String(), nullable=False, server_default=""),
        )
    if "last_name" not in columns:
        op.add_column("user_profile", sa.Column("last_name", sa.String(), nullable=True))

    # Backfill from the legacy single column while it still exists.
    if "full_name" in _columns("user_profile"):
        connection = op.get_bind()
        rows = connection.execute(sa.text("SELECT id, full_name FROM user_profile")).fetchall()
        for row in rows:
            first_name, last_name = _split(row.full_name)
            connection.execute(
                sa.text(
                    "UPDATE user_profile SET first_name = :first_name, last_name = :last_name WHERE id = :id"
                ),
                {"first_name": first_name, "last_name": last_name, "id": row.id},
            )
        op.drop_column("user_profile", "full_name")


def downgrade() -> None:
    """Re-merge the split columns back into a single ``full_name``."""
    columns = _columns("user_profile")

    if "full_name" not in columns:
        op.add_column(
            "user_profile",
            sa.Column("full_name", sa.String(), nullable=False, server_default=""),
        )

    if "first_name" in _columns("user_profile"):
        connection = op.get_bind()
        rows = connection.execute(sa.text("SELECT id, first_name, last_name FROM user_profile")).fetchall()
        for row in rows:
            merged = " ".join(part for part in (row.first_name, row.last_name) if part)
            connection.execute(
                sa.text("UPDATE user_profile SET full_name = :full_name WHERE id = :id"),
                {"full_name": merged, "id": row.id},
            )

        op.drop_column("user_profile", "first_name")
        op.drop_column("user_profile", "last_name")
