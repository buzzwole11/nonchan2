"""An inbox for notifications (spec section 26).

Section 26's presets and quiet hours already exist as `services/notifications.may_notify`;
what was missing was anywhere for an allowed notification to go. This is that place. A row
here has already passed the preset — the inbox is the delivery in this build, and a push
channel, when one is wired up, is a second transport for the same rows.

Revision ID: 0013_notifications
Revises: 0012_mathcard_teaser
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_notifications"
down_revision: str | None = "0012_mathcard_teaser"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.UUID().with_variant(sa.String(length=36), "sqlite")

CATEGORIES = (
    "daily_abstract",
    "important_arrival",
    "saved_paper_update",
    "review_due",
    "new_math_card",
)


def upgrade() -> None:
    allowed = ", ".join(f"'{value}'" for value in CATEGORIES)
    op.create_table(
        "notifications",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"category IN ({allowed})", name="ck_category_notificationcategory"),
        sa.UniqueConstraint("user_id", "category", "entity_id", name="uq_notification_subject"),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
