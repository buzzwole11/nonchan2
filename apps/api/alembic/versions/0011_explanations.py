"""Somewhere to keep AI explanations, marked as AI explanations (spec sections 8, 21, 23).

Section 8 asks for Before you read and Why it matters, and ends both with AI生成である
ことを明示する. Section 0 requires that distinction to exist in the data model rather than
only in the interface — which is why this is a table of its own. Nothing that reads a paper
row can accidentally serve generated prose as the paper's own words, because reaching this
content takes a join somebody had to write.

`input_hash` from `GenerationProvenanceMixin` is the cache key and the audit key at the same
time: the same abstract under the same prompt version yields the same row, and an
explanation that later turns out to be wrong can be traced to exactly what produced it.

Revision ID: 0011_explanations
Revises: 0010_full_texts
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_explanations"
down_revision: str | None = "0010_full_texts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = sa.UUID().with_variant(sa.String(length=36), "sqlite")
_JSON = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "abstract_explanations",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("paper_id", _UUID, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("audience", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("items", _JSON, nullable=False),
        sa.Column(
            "provenance_kind",
            sa.String(length=32),
            nullable=False,
            server_default="ai_explanation",
        ),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        # Provenance (spec section 23): provider, model, prompt version, input hash.
        sa.Column("generation_provider", sa.String(length=64), nullable=False),
        sa.Column("generation_model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "paper_id", "kind", "audience", "prompt_version", name="uq_explanation_key"
        ),
        sa.CheckConstraint(
            "kind IN ('before_you_read', 'why_it_matters')", name="ck_explanation_kind"
        ),
        # Empty string rather than NULL for the audience-less kind: PostgreSQL treats two
        # NULLs as distinct in a unique constraint, so a nullable column here would let two
        # `before_you_read` rows for the same paper exist side by side.
        sa.CheckConstraint(
            "(kind = 'why_it_matters' AND audience <> '')"
            " OR (kind = 'before_you_read' AND audience = '')",
            name="ck_explanation_audience",
        ),
    )
    op.create_index("ix_explanations_paper", "abstract_explanations", ["paper_id"])
    op.create_index("ix_abstract_explanations_input_hash", "abstract_explanations", ["input_hash"])


def downgrade() -> None:
    op.drop_index("ix_abstract_explanations_input_hash", table_name="abstract_explanations")
    op.drop_index("ix_explanations_paper", table_name="abstract_explanations")
    op.drop_table("abstract_explanations")
