"""The ANN column and index (DECISIONS.md D-006, migration 0009).

`vector_json` is the record and `vector_ann` is the index. Two copies of the same numbers is
a drift risk, so most of these tests are about the two never disagreeing — a row whose index
entry differed from its record would return the wrong neighbours and nothing would say so.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from papermatch_api.models import ANN_DIMENSIONS, Embedding, Paper
from papermatch_api.providers.local_embedding import MODEL_NAME, MODEL_VERSION, cosine, embed
from papermatch_api.services.embeddings import (
    embedding_text,
    nearest_papers,
    store_paper_embedding,
)
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]


def _paper(session: Session, slug: str, abstract: str) -> Paper:
    row = Paper(
        canonical_id=f"test:ann-{slug}",
        title=f"Paper {slug}",
        normalized_title=f"paper {slug}",
        abstract=abstract,
        authors=[],
        year=2026,
        source_provider="mock",
        source_url=f"https://example.invalid/{slug}",
        acquired_at=datetime.now(tz=UTC),
    )
    session.add(row)
    session.flush()
    return row


def test_the_extension_and_index_exist(db_session: Session) -> None:
    extension = db_session.execute(
        text("select extname from pg_extension where extname = 'vector'")
    ).scalar_one_or_none()
    index = db_session.execute(
        text("select indexname from pg_indexes where indexname = 'ix_embeddings_vector_ann'")
    ).scalar_one_or_none()

    assert extension == "vector"
    assert index == "ix_embeddings_vector_ann"


def test_storing_an_embedding_fills_both_the_record_and_the_index(db_session: Session) -> None:
    # Written in one place so they cannot drift. A row whose index entry disagreed with its
    # record would return the wrong neighbours and nothing would say so.
    paper = _paper(db_session, "both", "Markov chain mixing times and cutoff.")
    row = store_paper_embedding(db_session, paper)
    db_session.flush()

    assert row.vector_ann is not None
    assert len(row.vector_json) == ANN_DIMENSIONS
    assert [round(v, 6) for v in row.vector_ann] == [round(v, 6) for v in row.vector_json]


def test_re_embedding_updates_the_index_too(db_session: Session) -> None:
    # The path that would silently leave a stale index entry behind.
    paper = _paper(db_session, "changed", "Original abstract about graphs.")
    store_paper_embedding(db_session, paper)
    db_session.flush()

    paper.abstract = "A completely different abstract about fluid dynamics."
    row = store_paper_embedding(db_session, paper)
    db_session.flush()

    assert row.vector_ann is not None
    assert [round(v, 6) for v in row.vector_ann] == [round(v, 6) for v in row.vector_json]


def test_the_nearest_paper_is_the_one_that_reads_alike(db_session: Session) -> None:
    subject = _paper(db_session, "subject", "Concentration inequalities for Markov chains.")
    alike = _paper(db_session, "alike", "Concentration inequalities and Markov chain cutoff.")
    unlike = _paper(db_session, "unlike", "Morphological inflection in low-resource languages.")
    for paper in (subject, alike, unlike):
        store_paper_embedding(db_session, paper)
    db_session.flush()

    found = nearest_papers(db_session, embed(embedding_text(subject)), limit=2, exclude=subject.id)

    assert found
    assert found[0][0] == alike.id


def test_similarity_is_returned_not_distance(db_session: Session) -> None:
    # Every other module here talks about similarity. A function returning the opposite
    # ordering under a similar name is the kind of thing that is wrong for months.
    paper = _paper(db_session, "self", "Concentration inequalities for Markov chains.")
    store_paper_embedding(db_session, paper)
    db_session.flush()

    vector = embed(embedding_text(paper))
    found = nearest_papers(db_session, vector, limit=1)

    assert found
    assert found[0][1] == pytest.approx(cosine(vector, vector), abs=1e-6)


def test_a_vector_of_the_wrong_width_returns_nothing_rather_than_failing(
    db_session: Session,
) -> None:
    # A caller mistake must not take down a feed request, and an empty neighbour list
    # degrades to "no similarity information", which the scorer already handles.
    assert nearest_papers(db_session, [0.1, 0.2, 0.3]) == []


def test_only_this_model_is_searched(db_session: Session) -> None:
    # The reason `model` and `version` are in the unique key: mixing vector spaces breaks
    # distance quietly rather than loudly.
    paper = _paper(db_session, "othermodel", "Some abstract.")
    vector = embed(embedding_text(paper))
    db_session.add(
        Embedding(
            entity_type="paper",
            entity_id=paper.id,
            model="some-other-model",
            version=MODEL_VERSION,
            dimensions=len(vector),
            vector_json=vector,
            vector_ann=vector,
        )
    )
    db_session.flush()

    found = nearest_papers(db_session, vector, limit=10)

    assert paper.id not in {entity_id for entity_id, _ in found}
    assert MODEL_NAME != "some-other-model"
