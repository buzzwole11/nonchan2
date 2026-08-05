"""Storing and reading paper vectors (spec sections 13, 16).

One rule shapes everything here: **a vector is only comparable to another vector from the
same model and version.** `embeddings` is keyed on both for that reason, and this module
never mixes them — reading always names the model it wants, so a half-finished re-embedding
produces fewer comparisons rather than wrong ones.

The text a paper is embedded from is its title and abstract, in that order. Not the
segments, not the field labels: the abstract is what the reader is deciding on, so
similarity should mean "these two cards would read alike", which is exactly the judgement
the recent-similarity penalty in section 16 is trying to make.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import ANN_DIMENSIONS, Embedding, Paper
from papermatch_api.providers.local_embedding import (
    DIMENSIONS,
    MODEL_NAME,
    MODEL_VERSION,
    embed,
)

__all__ = ["embedding_text", "embeddings_for", "nearest_papers", "store_paper_embedding"]


def embedding_text(paper: Paper) -> str:
    return f"{paper.title}\n\n{paper.abstract}"


def _ann(vector: list[float]) -> list[float] | None:
    """The indexable copy, or None when this vector cannot go in the column.

    Written in the same place as `vector_json` so the two cannot drift: a row whose index
    entry disagreed with its record would return the wrong neighbours and nothing would say
    so. A width the column cannot hold yields None rather than a truncated vector — the
    honest outcome is "not indexed", not "indexed at the wrong coordinates".
    """
    return vector if len(vector) == ANN_DIMENSIONS else None


def store_paper_embedding(session: Session, paper: Paper) -> Embedding:
    """Compute and store one paper's vector, replacing any earlier one for this model.

    Replacing rather than appending: the unique key is (entity, model, version), so a
    second row for the same key would fail the constraint — and an abstract that changed
    because a v2 replaced a v1 should not leave the old vector behind to be compared
    against.
    """
    vector = embed(embedding_text(paper))
    existing = session.execute(
        select(Embedding).where(
            Embedding.entity_type == "paper",
            Embedding.entity_id == paper.id,
            Embedding.model == MODEL_NAME,
            Embedding.version == MODEL_VERSION,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.vector_json = vector
        existing.dimensions = len(vector)
        existing.vector_ann = _ann(vector)
        return existing

    row = Embedding(
        entity_type="paper",
        entity_id=paper.id,
        model=MODEL_NAME,
        version=MODEL_VERSION,
        dimensions=len(vector) or DIMENSIONS,
        vector_json=vector,
        vector_ann=_ann(vector),
    )
    session.add(row)
    return row


def embeddings_for(session: Session, paper_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[float]]:
    """Vectors for the papers that have one, from this model only.

    A paper with no vector is simply absent. The scorer treats a missing embedding as "no
    similarity information" rather than "no similarity", which is the honest reading — a
    paper ingested before the embedder existed is not thereby unlike everything.
    """
    if not paper_ids:
        return {}
    rows = session.execute(
        select(Embedding).where(
            Embedding.entity_type == "paper",
            Embedding.entity_id.in_(paper_ids),
            Embedding.model == MODEL_NAME,
            Embedding.version == MODEL_VERSION,
        )
    ).scalars()
    return {row.entity_id: list(row.vector_json) for row in rows}


def nearest_papers(
    session: Session, vector: list[float], *, limit: int = 10, exclude: uuid.UUID | None = None
) -> list[tuple[uuid.UUID, float]]:
    """The closest papers by cosine distance, using the ANN index (migration 0009).

    Returns `(paper_id, similarity)` with similarity in [-1, 1], **not** the distance
    pgvector works in: every other module in this codebase talks about similarity, and a
    function that returned the opposite ordering under a similar name is the kind of thing
    that is wrong for months.

    Only rows from this model and version are considered — the same rule `embeddings_for`
    follows, and the reason `model` and `version` are in the unique key. A vector of the
    wrong width returns nothing rather than an error: it is a caller mistake that must not
    take down a feed request, and an empty neighbour list degrades to "no similarity
    information", which the scorer already handles.
    """
    if len(vector) != ANN_DIMENSIONS:
        return []

    distance = Embedding.vector_ann.cosine_distance(vector).label("distance")
    rows = session.execute(
        select(Embedding.entity_id, distance)
        .where(
            Embedding.entity_type == "paper",
            Embedding.model == MODEL_NAME,
            Embedding.version == MODEL_VERSION,
            Embedding.vector_ann.is_not(None),
            *([Embedding.entity_id != exclude] if exclude is not None else []),
        )
        .order_by(distance)
        .limit(limit)
    ).all()
    return [(entity_id, 1.0 - float(dist)) for entity_id, dist in rows]
