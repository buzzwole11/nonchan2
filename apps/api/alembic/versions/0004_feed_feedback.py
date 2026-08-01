"""The three feed-feedback actions section 16 asks for but the vocabulary lacked.

Section 16 lists five feedback controls. Two of them (`hide_topic`, `hide_author`) have
existed since the initial schema; the other three — 類似論文を減らす / 実験系を増やす /
古典的論文を増やす — had no action type, so the buttons could not have been wired to
anything. This adds them.

They are actions rather than settings columns on purpose. Section 16 is explicit that
negative feedback means 「今回は見送る」 and not 「嫌い」, and an action is the thing this
schema already knows how to expire and undo: the feed counts only actions that are not
undone and fall inside the suppression window, so Undo and the passage of time both work
without any further bookkeeping (DECISIONS.md D-019).

The CHECK constraint swap is written by hand: Alembic's autogenerate does not compare check
constraints, so a vocabulary change never appears in a generated migration. This is the
documented cost of the VARCHAR + CHECK choice in DECISIONS.md D-003, and
``tests/test_vocab_parity.py`` is what catches a missed one.

Revision ID: 0004_feed_feedback
Revises: 0003_learning
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_feed_feedback"
down_revision: str | None = "0003_learning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTION_TYPE = (
    "action_type IN ('skip', 'save', 'open_source', 'translate', 'expand_math', "
    "'hide_topic', 'hide_author', 'undo')"
)
NEW_ACTION_TYPE = (
    "action_type IN ('skip', 'save', 'open_source', 'translate', 'expand_math', "
    "'hide_topic', 'hide_author', 'less_similar', 'more_experimental', 'more_classic', "
    "'undo')"
)


def upgrade() -> None:
    op.drop_constraint("ck_action_type_actiontype", "actions", type_="check")
    op.create_check_constraint("ck_action_type_actiontype", "actions", NEW_ACTION_TYPE)


def downgrade() -> None:
    # Rows carrying the new types would violate the old constraint. They are deleted rather
    # than relabelled: unlike the `heuristic` → `ai` swap in 0003, there is no older value
    # that means the same thing, and rewriting a reader's 「実験系を増やす」 into some other
    # action would put a request in their audit log that they never made.
    op.execute(
        sa.text(
            "DELETE FROM actions WHERE action_type IN "
            "('less_similar', 'more_experimental', 'more_classic')"
        )
    )
    op.drop_constraint("ck_action_type_actiontype", "actions", type_="check")
    op.create_check_constraint("ck_action_type_actiontype", "actions", OLD_ACTION_TYPE)
