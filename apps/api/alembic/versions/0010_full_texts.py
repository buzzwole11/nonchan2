"""Somewhere to keep a paper's body, when the licence permits it (spec sections 17, 21).

Section 17's `contrasting` label needs a sentence in one paper that refers to another, and
there was nowhere to keep the text those sentences come from. The maths pipeline already
parses bodies, but it did so from the provider on demand and kept nothing.

**A row here is a licence decision that already went the right way.** `services/fulltext
.licence_decision` is the gate, and nothing reaches this table without passing it — which is
why the licence is stored alongside the body rather than only in the paper's metadata. The
two are different things: arXiv metadata is CC0 while the manuscript is under the author's
own terms, and conflating them is the mistake the gate exists to prevent.

**One body per paper.** A second row for the same paper would mean two answers to "what does
this paper say", and every reader of the table would have to pick one.

Revision ID: 0010_full_texts
Revises: 0009_pgvector
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_full_texts"
down_revision: str | None = "0009_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.UUID().with_variant(sa.String(length=36), "sqlite")


def upgrade() -> None:
    op.create_table(
        "paper_full_texts",
        sa.Column("paper_id", _UUID, nullable=False),
        sa.Column("body_format", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        # The licence of the BODY, not of the paper's metadata (spec section 21).
        sa.Column("license_id", sa.String(length=64), nullable=False),
        sa.Column("license_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("paper_id"),
        sa.CheckConstraint("body_format IN ('latex', 'jats_xml')", name="ck_full_text_format"),
        # Not nullable and not empty: a row whose licence is unknown must not exist here at
        # all, because its existence is what says the body may be used.
        sa.CheckConstraint("length(license_id) > 0", name="ck_full_text_license_present"),
    )


def downgrade() -> None:
    op.drop_table("paper_full_texts")
