"""Give the notification-preset CHECK the name the model gives it.

`models.vocab_check` names every vocabulary constraint `ck_<column>_<vocabulary>`, and
`user_settings.notification_preset` is the one place the migration disagreed: 0007 wrote it
by hand as `ck_notification_preset`. Both spellings guard the same values, so nothing was
ever unprotected — but the names differed, and the drift test compares models against a
migrated database. It stayed hidden because Alembic did not compare CHECK constraints when
0007 was written; a newer Alembic does, and the disagreement surfaced on the first fresh
install. Renaming is enough: the constraint keeps its definition and its rows.

Revision ID: 0014_notification_preset_check
Revises: 0013_notifications
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_notification_preset_check"
down_revision: str | None = "0013_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_NAME = "ck_notification_preset"
NEW_NAME = "ck_notification_preset_notificationpreset"
TABLE = "user_settings"


def upgrade() -> None:
    # SQLite cannot rename a constraint, and the whole schema is PostgreSQL in every
    # environment that runs migrations; the drift test runs against PostgreSQL too.
    op.execute(f"ALTER TABLE {TABLE} RENAME CONSTRAINT {OLD_NAME} TO {NEW_NAME}")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} RENAME CONSTRAINT {NEW_NAME} TO {OLD_NAME}")
