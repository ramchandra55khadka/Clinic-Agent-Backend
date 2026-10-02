"""Add contact/personal details to user_profile.

The profile is now the sole home of personal data (it is no longer reachable
through an ORM relationship from ``user_account``), so it also keeps a copy of
the account email plus the optional ``date_of_birth``, ``gender`` and ``address``
fields.

Revision ID: 0014_profile_contact_details
Revises: 0013_split_profile_name
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_profile_contact_details"
down_revision: str | None = "0013_split_profile_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    """Add the profile's copied email and optional personal-detail columns."""
    columns = _columns("user_profile")

    if "email" not in columns:
        op.add_column("user_profile", sa.Column("email", sa.String(), nullable=True))
        op.create_index("ix_user_profile_email", "user_profile", ["email"])

    if "date_of_birth" not in columns:
        op.add_column("user_profile", sa.Column("date_of_birth", sa.Date(), nullable=True))
    if "gender" not in columns:
        op.add_column("user_profile", sa.Column("gender", sa.String(), nullable=True))
    if "address" not in columns:
        op.add_column("user_profile", sa.Column("address", sa.Text(), nullable=True))

    # Backfill the copied email for profiles that already belong to an account.
    if "user_id" in _columns("user_profile"):
        connection = op.get_bind()
        connection.execute(
            sa.text(
                "UPDATE user_profile "
                "SET email = ("
                "  SELECT user_account.email FROM user_account "
                "  WHERE user_account.id = user_profile.user_id"
                ") "
                "WHERE email IS NULL AND user_id IS NOT NULL"
            )
        )


def downgrade() -> None:
    """Drop the columns added by this migration."""
    columns = _columns("user_profile")

    if "email" in columns:
        indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("user_profile")}
        if "ix_user_profile_email" in indexes:
            op.drop_index("ix_user_profile_email", table_name="user_profile")
        op.drop_column("user_profile", "email")

    for name in ("date_of_birth", "gender", "address"):
        if name in _columns("user_profile"):
            op.drop_column("user_profile", name)
