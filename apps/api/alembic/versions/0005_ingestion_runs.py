"""Durable state for the ingestion worker.

Two spec requirements need somewhere to remember things between runs.

Section 21 asks that 削除・訂正・撤回情報を反映できる — the sources we copy from change
after we copy from them, so there has to be a second kind of run that goes back and asks
again, on its own schedule.

Section 27 lists 同一ソースへの過剰APIアクセス as a guardrail. Without a stored cursor,
every restart would begin at the first page of every source, which is precisely the
behaviour that guardrail exists to catch.

A run row is both the record of what happened and the state the next run reads. The
operator asking "why has nothing new appeared since Tuesday" and the scheduler asking
"where do I start" want the same row, so they get the same row.

Revision ID: 0005_ingestion_runs
Revises: 0004_feed_feedback
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_ingestion_runs"
down_revision: str | None = "0004_feed_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.UUID().with_variant(sa.String(length=36), "sqlite"), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("job", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="discovery"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column(
            "counts",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_ingestion_run_status"
        ),
        sa.CheckConstraint("kind IN ('discovery', 'refresh')", name="ck_ingestion_run_kind"),
    )
    # Every scheduler decision is "the newest successful run of this job", so the index
    # carries the three columns that question names, in that order.
    op.create_index(
        "ix_ingestion_runs_job", "ingestion_runs", ["source", "job", "started_at"], unique=False
    )

    # Separate from `acquired_at`, which section 21 defines as provenance the provider
    # supplies. The refresh queue needs our own note of when we last checked: ordering by
    # provider-supplied timestamps means a source that reports anything other than our fetch
    # time keeps its papers permanently "stale", and the queue re-checks one batch forever.
    op.add_column(
        "papers", sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_papers_refresh_queue", "papers", ["source_provider", "last_refreshed_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_papers_refresh_queue", table_name="papers")
    op.drop_column("papers", "last_refreshed_at")
    op.drop_index("ix_ingestion_runs_job", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
