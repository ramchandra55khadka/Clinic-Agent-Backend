"""Add optional profile photo to user accounts.

Revision ID: 0005_profile_photo_url
Revises: 0004_user_id_string_columns
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_profile_photo_url"
down_revision: str | None = "0004_user_id_string_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if not _has_column("user_account", "profile_photo_url"):
        op.add_column("user_account", sa.Column("profile_photo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("user_account", "profile_photo_url"):
        op.drop_column("user_account", "profile_photo_url")
