"""Expression review scheduling, and `heuristic` as a detection method.

Two changes for Phase 2 (spec sections 8 and 9):

* ``expression_cards`` gains the kind, context and review columns it needs to be a
  personal academic-English dictionary rather than a list of strings.
* ``abstract_segments.detected_by`` accepts ``heuristic``. A rule-based classifier is not
  an AI one, and labelling its output ``ai`` would claim more for it than it is worth
  (spec section 8: AI分類の場合は自動検出ラベルを付ける — the label has to be accurate).

The CHECK constraint swap is written by hand: Alembic's autogenerate does not compare
check constraints, so a vocabulary change never appears in a generated migration. This is
the documented cost of the VARCHAR + CHECK choice in DECISIONS.md D-003, and
``tests/test_vocab_parity.py`` is what catches a missed one.

Revision ID: 0003_learning
Revises: 0002_action_sequence
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_learning"
down_revision: str | None = "0002_action_sequence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DETECTED_BY = "detected_by IN ('ai', 'source', 'human')"
NEW_DETECTED_BY = "detected_by IN ('source', 'heuristic', 'ai', 'human')"


def upgrade() -> None:
    # -- expression cards --------------------------------------------------------
    op.add_column(
        "expression_cards",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="word"),
    )
    op.add_column("expression_cards", sa.Column("context", sa.Text(), nullable=True))
    op.add_column(
        "expression_cards",
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "expression_cards", sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "expression_cards", sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_expressions_due", "expression_cards", ["user_id", "next_review_at"], unique=False
    )
    op.create_unique_constraint(
        "uq_expression_user_phrase", "expression_cards", ["user_id", "phrase"]
    )
    op.create_check_constraint(
        "ck_kind_expressionkind",
        "expression_cards",
        "kind IN ('word', 'collocation', 'pattern', 'sentence')",
    )
    # The server defaults existed only to backfill; the application supplies both.
    op.alter_column("expression_cards", "kind", server_default=None)
    op.alter_column("expression_cards", "review_count", server_default=None)

    # -- detection method --------------------------------------------------------
    op.drop_constraint("ck_segment_detected_by", "abstract_segments", type_="check")
    op.create_check_constraint(
        "ck_detected_by_detectionmethod", "abstract_segments", NEW_DETECTED_BY
    )


def downgrade() -> None:
    # Rows labelled `heuristic` would violate the old constraint, so they are relabelled
    # rather than left to fail the ALTER.
    op.execute(
        sa.text("UPDATE abstract_segments SET detected_by = 'ai' WHERE detected_by = 'heuristic'")
    )
    op.drop_constraint("ck_detected_by_detectionmethod", "abstract_segments", type_="check")
    op.create_check_constraint("ck_segment_detected_by", "abstract_segments", OLD_DETECTED_BY)

    op.drop_constraint("ck_kind_expressionkind", "expression_cards", type_="check")
    op.drop_constraint("uq_expression_user_phrase", "expression_cards", type_="unique")
    op.drop_index("ix_expressions_due", table_name="expression_cards")
    op.drop_column("expression_cards", "next_review_at")
    op.drop_column("expression_cards", "last_reviewed_at")
    op.drop_column("expression_cards", "review_count")
    op.drop_column("expression_cards", "context")
    op.drop_column("expression_cards", "kind")
