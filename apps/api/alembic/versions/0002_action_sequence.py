"""Add a monotonic sequence to actions.

``created_at`` uses ``now()``, which in PostgreSQL is the *transaction* clock: two actions
written inside one request share a timestamp, so "the most recent action" — the one Undo
reverses (spec section 6) — could not be determined. ``sequence`` is assigned by a
database sequence at insert time and gives that a definite answer.

Autogenerate emits the ``nextval`` default but not the ``CREATE SEQUENCE`` behind it, and
leaves the unique constraint unnamed, so both are written out here.

Revision ID: 0002_action_sequence
Revises: 0001_initial
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_action_sequence"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEQUENCE_NAME = "actions_sequence_seq"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {SEQUENCE_NAME}"))
    op.add_column(
        "actions",
        sa.Column(
            "sequence",
            sa.BigInteger(),
            server_default=sa.text(f"nextval('{SEQUENCE_NAME}')"),
            nullable=False,
        ),
    )
    op.create_index("ix_actions_user_sequence", "actions", ["user_id", "sequence"], unique=False)
    op.create_unique_constraint("uq_actions_sequence", "actions", ["sequence"])
    # Tie the sequence's lifetime to the column so a later DROP COLUMN cleans up after
    # itself instead of leaving an orphan sequence behind.
    op.execute(sa.text(f"ALTER SEQUENCE {SEQUENCE_NAME} OWNED BY actions.sequence"))


def downgrade() -> None:
    op.drop_constraint("uq_actions_sequence", "actions", type_="unique")
    op.drop_index("ix_actions_user_sequence", table_name="actions")
    op.drop_column("actions", "sequence")
    op.execute(sa.text(f"DROP SEQUENCE IF EXISTS {SEQUENCE_NAME}"))
