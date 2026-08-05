"""Somewhere to keep a password, and the reader's notification preset.

Two columns that were named in the spec and had nowhere to live.

`users.password_hash` is for section 24's `POST /auth/login`. Nullable, and it stays null for
every guest: section 4 puts the first Abstract card before any sign-up, so an account without
a password is the normal state rather than an incomplete one.

`user_settings.notification_preset` is section 26's プリセット. It defaults to `quiet` rather
than to the most talkative option — a default that notifies is a decision made on the
reader's behalf about their attention, and `none` is one tap away.

Revision ID: 0007_login_and_notifications
Revises: 0006_content_reports
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_login_and_notifications"
down_revision: str | None = "0006_content_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRESETS = ("none", "quiet", "daily", "weekdays", "important_only")


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "user_settings",
        sa.Column(
            "notification_preset",
            sa.String(length=32),
            nullable=False,
            server_default="quiet",
        ),
    )
    op.create_check_constraint(
        "ck_notification_preset",
        "user_settings",
        sa.column("notification_preset").in_(PRESETS),
    )


def downgrade() -> None:
    op.drop_constraint("ck_notification_preset", "user_settings", type_="check")
    op.drop_column("user_settings", "notification_preset")
    op.drop_column("users", "password_hash")
