"""Use UUID strings for user account primary keys.

Revision ID: 0003_user_uuid_primary_keys
Revises: 0002_production_hardening
Create Date: 2026-09-18

This project moved account identifiers from sequential integers to UUID strings.
For existing production databases with integer user IDs, perform a data migration
that maps each old integer ID to a generated UUID and updates user_auth,
refresh_token and audit_log before applying this schema state. Fresh databases
created from 0001+ already use String(36) IDs after this revision series.
"""

from collections.abc import Sequence

revision: str = "0003_user_uuid_primary_keys"
down_revision: str | None = "0002_production_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Intentionally no-op for fresh databases. Existing integer-ID databases need
    # an explicit data migration because primary-key type changes are destructive
    # across SQLite/Postgres/MySQL without a generated ID mapping table.
    pass


def downgrade() -> None:
    # UUID user IDs are the forward schema standard.
    pass
