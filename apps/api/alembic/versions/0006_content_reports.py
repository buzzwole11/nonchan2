"""Somewhere for a reader to say a maths card looks wrong.

Section 12 ends its pipeline with 必要なカードのみ人手レビューへ送る and section 27 counts
AI説明の問題報告率 as a guardrail. Both need a reader to be able to report a problem, and the
app had nowhere to put one.

Not `review_events`. That table holds a *decision* — approved / rejected / needs_changes —
made by someone with the standing to make it. This holds a *report*, from a reader who has
no authority over what happens next and should not be handed the vocabulary of one. Sharing
a table would make "approved" something an anonymous guest can assert.

Revision ID: 0006_content_reports
Revises: 0005_ingestion_runs
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_content_reports"
down_revision: str | None = "0005_ingestion_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.UUID().with_variant(sa.String(length=36), "sqlite")

REPORT_REASONS = (
    "formula_differs_from_paper",
    "step_wrong",
    "explanation_wrong",
    "symbol_wrong",
    "rendering_broken",
    "other",
)
REPORT_STATUSES = ("new", "triaged", "resolved")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "content_reports",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", _UUID, nullable=False),
        sa.Column(
            "math_card_id",
            _UUID,
            sa.ForeignKey("math_cards.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(length=48), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "entity_type IN ('math_card', 'derivation_step', 'equation')",
            name="ck_content_report_entity_type",
        ),
        sa.CheckConstraint(_in_list("reason", REPORT_REASONS), name="ck_reason_reportreason"),
        sa.CheckConstraint(_in_list("status", REPORT_STATUSES), name="ck_status_reportstatus"),
        # One report per reader per problem per thing. Section 27's metric is a *rate*, and
        # a reader tapping twice is not two readers.
        sa.UniqueConstraint(
            "user_id", "entity_type", "entity_id", "reason", name="uq_content_report_once"
        ),
    )
    op.create_index(
        "ix_content_reports_entity", "content_reports", ["entity_type", "entity_id"], unique=False
    )
    # The review queue reads "oldest unhandled first", which is this index exactly.
    op.create_index(
        "ix_content_reports_status", "content_reports", ["status", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_content_reports_status", table_name="content_reports")
    op.drop_index("ix_content_reports_entity", table_name="content_reports")
    op.drop_table("content_reports")
