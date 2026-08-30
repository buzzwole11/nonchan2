"""The `vector` column and its ANN index (DECISIONS.md D-006).

D-006 deferred this to Phase 3 because the dimension is decided by the embedding model, and
a number burned into the schema before that choice is a migration to redo. The model is now
`papermatch-hashed-bow` at 512 dimensions, so the number is knowable.

**`vector_json` stays and remains the record.** The new column is an *index*, not a second
copy of the truth: everything that reads a vector still reads the JSON, and this exists so
PostgreSQL can answer "nearest to this" without loading every row. Dropping the JSON would
tie the stored data to one extension being installed.

**Only rows of this dimension are backfilled.** A `vector(512)` column cannot hold a
384-dimension vector, and coercing one would be inventing coordinates. Rows from another
model keep their JSON and simply have no ANN entry — which is correct, because they are not
comparable to these anyway (the unique key includes `model` and `version` for that reason).

**Cosine ops.** `services/scoring.py` and `metrics.py` compare with cosine; an index built
for L2 would answer a different question and quietly return a different neighbour set.

Revision ID: 0009_pgvector
Revises: 0008_resurface_action
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_pgvector"
down_revision: str | None = "0008_resurface_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `providers/local_embedding.DIMENSIONS`. A model with a different width needs its own
#: column and its own index; it cannot share this one.
DIMENSIONS = 512


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(sa.text(f"ALTER TABLE embeddings ADD COLUMN vector_ann vector({DIMENSIONS})"))
    # Backfill from the JSON that is already there. `vector` parses the same bracketed list
    # PostgreSQL renders a JSON array as, so this needs no application pass.
    op.execute(
        sa.text(
            "UPDATE embeddings SET vector_ann = vector_json::text::vector "
            f"WHERE dimensions = {DIMENSIONS}"
        )
    )
    # HNSW rather than IVFFlat: it needs no training pass over existing rows, which matters
    # for a table that starts empty and fills as papers are ingested.
    op.execute(
        sa.text(
            "CREATE INDEX ix_embeddings_vector_ann ON embeddings "
            "USING hnsw (vector_ann vector_cosine_ops)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_embeddings_vector_ann"))
    op.execute(sa.text("ALTER TABLE embeddings DROP COLUMN IF EXISTS vector_ann"))
    # The extension is left installed. Dropping it would break any other database in the
    # cluster using it, and it costs nothing to leave.
