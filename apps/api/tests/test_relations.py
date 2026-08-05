"""Classifying how two papers are related (spec section 17).

Almost every test here is about a label *not* being produced. Section 17's rule —
単なる類似度だけで関係ラベルを断定しない — is a rule about restraint, and restraint is only
testable by asking for the wrong answer and checking it does not come back.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from papermatch_api.models import Paper, PaperIdentifier, PaperRelation, SavedPaper, User
from papermatch_api.services.embeddings import store_paper_embedding
from papermatch_api.services.relations import (
    RELATED_SIMILARITY,
    Candidate,
    Mention,
    candidate_pool,
    candidates_for,
    cited_openalex_ids,
    classify,
    classify_all,
    relations_for,
)
from tests.conftest import requires_db

# ------------------------------------------------------------------ what similarity may say


def test_two_alike_abstracts_are_related_and_nothing_stronger() -> None:
    # The one conclusion similarity is allowed to reach on its own.
    result = classify(2026, Candidate(paper_id="p", year=2025, similarity=0.81))

    assert result is not None
    assert result.relation_type == "related"
    assert result.evidence["basis"] == "similarity"


def test_an_older_similar_paper_is_not_called_foundational() -> None:
    # This is the mistake the section exists to prevent. "Alike, and published earlier" is
    # not "this is what the paper is built on" — it is two papers about Markov chains.
    result = classify(2026, Candidate(paper_id="p", year=1998, similarity=0.9))

    assert result is not None
    assert result.relation_type == "related"


def test_a_newer_similar_paper_is_not_called_a_follow_up() -> None:
    result = classify(2020, Candidate(paper_id="p", year=2026, similarity=0.9))

    assert result is not None
    assert result.relation_type == "related"


def test_similarity_never_produces_contrasting_however_high() -> None:
    # Nothing about "these read alike" can mean "these disagree".
    result = classify(2026, Candidate(paper_id="p", year=2026, similarity=0.99))

    assert result is not None
    assert result.relation_type != "contrasting"


def test_a_weak_similarity_produces_no_relation_at_all() -> None:
    # Not a low-confidence `related`: a list of everything is a list of nothing, and the
    # reader stops reading it — taking the well-evidenced labels down with it.
    assert classify(2026, Candidate(paper_id="p", year=2025, similarity=0.2)) is None


def test_similarity_stays_below_the_citation_backed_labels() -> None:
    # The confidence is what the UI sorts on, so a weaker claim has to carry a smaller
    # number or the ordering quietly lies.
    similar = classify(2026, Candidate(paper_id="p", year=2025, similarity=0.95))
    cited = classify(2026, Candidate(paper_id="q", year=2019, anchor_cites_candidate=True))

    assert similar is not None and cited is not None
    assert similar.confidence < cited.confidence


def test_a_pair_with_no_evidence_of_any_kind_is_not_a_relation() -> None:
    assert classify(2026, Candidate(paper_id="p", year=2025)) is None


# ------------------------------------------------------------------ citation direction


def test_a_paper_the_anchor_cites_is_foundational() -> None:
    result = classify(2026, Candidate(paper_id="p", year=2011, anchor_cites_candidate=True))

    assert result is not None
    assert result.relation_type == "foundational"
    assert result.evidence["citation"] == "anchor_cites_candidate"
    assert result.evidence["basis"] == "citation"


def test_a_paper_that_cites_the_anchor_is_a_follow_up() -> None:
    result = classify(2019, Candidate(paper_id="p", year=2026, candidate_cites_anchor=True))

    assert result is not None
    assert result.relation_type == "follow_up"
    assert result.evidence["citation"] == "candidate_cites_anchor"


def test_the_direction_is_read_from_the_citation_not_from_the_dates() -> None:
    # A preprint can cite something that appears in print later. The citation list knows who
    # built on whom; the dates only know what was announced when. Reading direction from the
    # dates would point the reader at the wrong end of the literature.
    result = classify(2026, Candidate(paper_id="p", year=2027, anchor_cites_candidate=True))

    assert result is not None
    assert result.relation_type == "foundational"
    assert result.evidence["publicationOrderAgrees"] is False


def test_a_citation_whose_dates_disagree_is_reported_with_lower_confidence() -> None:
    agreeing = classify(2026, Candidate(paper_id="p", year=2011, anchor_cites_candidate=True))
    disagreeing = classify(2026, Candidate(paper_id="q", year=2027, anchor_cites_candidate=True))

    assert agreeing is not None and disagreeing is not None
    assert disagreeing.confidence < agreeing.confidence


def test_a_citation_in_a_different_area_is_still_a_citation() -> None:
    # Low similarity does not overrule a reference list. Papers genuinely build on work from
    # elsewhere, and that is often the most interesting edge on the plane.
    result = classify(
        2026, Candidate(paper_id="p", year=2004, similarity=0.05, anchor_cites_candidate=True)
    )

    assert result is not None
    assert result.relation_type == "foundational"


def test_mutual_citations_with_no_publication_order_stay_related() -> None:
    # Two papers citing each other across versions is real. With no year to order them,
    # picking a direction would be inventing one.
    result = classify(
        None,
        Candidate(paper_id="p", anchor_cites_candidate=True, candidate_cites_anchor=True),
    )

    assert result is not None
    assert result.relation_type == "related"
    assert result.evidence["citation"] == "mutual"


def test_mutual_citations_use_the_publication_order_to_choose_a_direction() -> None:
    result = classify(
        2026,
        Candidate(
            paper_id="p", year=2011, anchor_cites_candidate=True, candidate_cites_anchor=True
        ),
    )

    assert result is not None
    assert result.relation_type == "foundational"


# ------------------------------------------------------------------ contrast


def test_contrast_requires_a_sentence_that_actually_draws_one() -> None:
    result = classify(
        2026,
        Candidate(
            paper_id="p",
            year=2024,
            similarity=0.7,
            mentions=(
                Mention(
                    source="anchor",
                    snippet="In contrast to Almeida et al., we obtain a bound with no log factor.",
                ),
            ),
        ),
    )

    assert result is not None
    assert result.relation_type == "contrasting"
    assert result.evidence["contrastCue"] == "in contrast"
    assert "Almeida" in result.evidence["mention"]["snippet"]


def test_a_plain_mention_is_related_rather_than_contrasting() -> None:
    # Being cited in a sentence is a connection. It is not a disagreement, and telling the
    # reader it is sends them looking for an argument that is not in the paper.
    result = classify(
        2026,
        Candidate(
            paper_id="p",
            year=2024,
            mentions=(Mention(source="anchor", snippet="We follow the approach of Zubkov."),),
        ),
    )

    assert result is not None
    assert result.relation_type == "related"
    assert result.evidence["basis"] == "mention"


def test_a_cue_word_used_in_an_ordinary_sentence_does_not_trigger_contrast() -> None:
    # "however large n becomes" is about asymptotics, not about disagreeing with anybody.
    # An earlier version matched bare "however" anywhere in the snippet and fired on this.
    result = classify(
        2026,
        Candidate(
            paper_id="p",
            year=2024,
            similarity=0.7,
            mentions=(
                Mention(source="anchor", snippet="The bound holds however large n becomes."),
            ),
        ),
    )

    assert result is not None
    assert result.relation_type != "contrasting"


def test_a_japanese_contrast_cue_is_recognised() -> None:
    result = classify(
        2026,
        Candidate(
            paper_id="p",
            year=2024,
            mentions=(
                Mention(source="anchor", snippet="先行研究とは対照的に、我々は上界を示す。"),
            ),
        ),
    )

    assert result is not None
    assert result.relation_type == "contrasting"


def test_contrast_outranks_a_citation_for_the_same_pair() -> None:
    # Both are true; "they disagree" is the more specific and more useful thing to say.
    result = classify(
        2026,
        Candidate(
            paper_id="p",
            year=2019,
            anchor_cites_candidate=True,
            mentions=(
                Mention(
                    source="anchor",
                    snippet="Unlike the construction of Rousseau, ours is explicit.",
                ),
            ),
        ),
    )

    assert result is not None
    assert result.relation_type == "contrasting"


# ------------------------------------------------------------------ the evidence itself


def test_every_relation_carries_what_produced_it() -> None:
    # Section 17: 引用方向、公開日、本文中の言及、モデル分類の根拠を保持する.
    result = classify(
        2026,
        Candidate(
            paper_id="p",
            year=2011,
            similarity=0.71,
            similarity_model="papermatch-local-hash",
            anchor_cites_candidate=True,
        ),
    )

    assert result is not None
    evidence = result.evidence
    assert evidence["citation"] == "anchor_cites_candidate"
    assert evidence["publicationOrder"] == "before"
    assert evidence["anchorYear"] == 2026
    assert evidence["candidateYear"] == 2011
    assert evidence["similarity"] == 0.71
    assert evidence["similarityModel"] == "papermatch-local-hash"


def test_absent_similarity_is_recorded_as_absent_not_as_zero() -> None:
    # Zero would read as "we compared them and they are unlike", which is a finding. Nothing
    # was compared.
    result = classify(2026, Candidate(paper_id="p", year=2011, anchor_cites_candidate=True))

    assert result is not None
    assert result.evidence["similarity"] is None


def test_an_unknown_year_leaves_the_publication_order_unstated() -> None:
    result = classify(None, Candidate(paper_id="p", similarity=0.9))

    assert result is not None
    assert result.evidence["publicationOrder"] is None


# ------------------------------------------------------------------ batches


def test_a_batch_drops_the_pairs_no_label_fits() -> None:
    results = classify_all(
        2026,
        [
            Candidate(paper_id="keep", year=2011, anchor_cites_candidate=True),
            Candidate(paper_id="drop", year=2025, similarity=0.1),
        ],
    )

    assert [paper_id for paper_id, _ in results] == ["keep"]


def test_a_batch_is_ordered_by_how_well_evidenced_each_relation_is() -> None:
    results = classify_all(
        2026,
        [
            Candidate(paper_id="similar", year=2025, similarity=0.9),
            Candidate(paper_id="cited", year=2011, anchor_cites_candidate=True),
        ],
    )

    assert [paper_id for paper_id, _ in results] == ["cited", "similar"]


def test_the_threshold_is_the_boundary_it_says_it_is() -> None:
    just_over = classify(2026, Candidate(paper_id="p", similarity=RELATED_SIMILARITY))
    just_under = classify(2026, Candidate(paper_id="p", similarity=RELATED_SIMILARITY - 0.01))

    assert just_over is not None
    assert just_under is None


# ------------------------------------------------------------------ against the database


def _paper(
    session: Session,
    *,
    slug: str,
    title: str = "A Paper",
    abstract: str = "Nothing in particular.",
    year: int = 2024,
    field_id: str | None = None,
    openalex: str | None = None,
    references: list[str] | None = None,
) -> Paper:
    raw: dict[str, object] = {}
    if references is not None:
        raw["referenced_works"] = [f"https://openalex.org/{value}" for value in references]
    row = Paper(
        canonical_id=f"test:{slug}",
        title=title,
        normalized_title=title.lower(),
        abstract=abstract,
        authors=[{"name": "A. Nonymous"}],
        year=year,
        primary_field_id=field_id,
        source_provider="openalex",
        source_url=f"https://example.invalid/{slug}",
        acquired_at=datetime.now(tz=UTC),
        raw_metadata=raw,
    )
    session.add(row)
    session.flush()
    if openalex is not None:
        session.add(PaperIdentifier(paper_id=row.id, kind="openalex", value=openalex))
        session.flush()
    return row


def test_a_reference_list_is_read_from_the_provider_record() -> None:
    paper = Paper(raw_metadata={"referenced_works": ["https://openalex.org/W1", "W2"]})

    assert cited_openalex_ids(paper) == {"W1", "W2"}


def test_a_provider_that_said_nothing_about_references_yields_nothing() -> None:
    # And the caller must not read this as "cites nothing" — see the citation flags below.
    assert cited_openalex_ids(Paper(raw_metadata={})) == set()


@pytest.mark.integration
@requires_db
def test_a_citation_between_two_ingested_papers_becomes_a_relation(db_session: Session) -> None:
    user = User(is_guest=True)
    db_session.add(user)
    db_session.flush()

    older = _paper(db_session, slug="older", year=2011, openalex="W100", field_id=None)
    anchor = _paper(db_session, slug="anchor", year=2026, references=["W100"])
    db_session.add(SavedPaper(user_id=user.id, paper_id=older.id, reasons=["interesting"]))
    db_session.flush()

    pairs = relations_for(db_session, anchor, user.id)

    assert [(p.canonical_id, r.relation_type) for p, r in pairs] == [("test:older", "foundational")]
    assert pairs[0][1].evidence["citation"] == "anchor_cites_candidate"


@pytest.mark.integration
@requires_db
def test_a_missing_reference_list_is_not_read_as_citing_nothing(db_session: Session) -> None:
    # Both papers are silent about their references, so no citation edge may be claimed in
    # either direction — the absence of data is not evidence of absence.
    user = User(is_guest=True)
    db_session.add(user)
    db_session.flush()

    other = _paper(db_session, slug="other", year=2011, openalex="W200")
    anchor = _paper(db_session, slug="anchor", year=2026)

    candidates = candidates_for(db_session, anchor, [other])

    assert candidates[0].anchor_cites_candidate is False
    assert candidates[0].candidate_cites_anchor is False


@pytest.mark.integration
@requires_db
def test_similarity_only_appears_when_both_papers_have_a_vector(db_session: Session) -> None:
    user = User(is_guest=True)
    db_session.add(user)
    db_session.flush()

    embedded = _paper(db_session, slug="embedded", abstract="Markov chain mixing times.")
    bare = _paper(db_session, slug="bare", abstract="Markov chain mixing times.")
    anchor = _paper(db_session, slug="anchor", abstract="Markov chain mixing times.")
    store_paper_embedding(db_session, embedded)
    store_paper_embedding(db_session, anchor)
    db_session.flush()

    by_id = {c.paper_id: c for c in candidates_for(db_session, anchor, [embedded, bare])}

    assert by_id[str(embedded.id)].similarity is not None
    # Not 0.0: nothing was compared, and a number here would read as "compared and unlike".
    assert by_id[str(bare.id)].similarity is None


@pytest.mark.integration
@requires_db
def test_re_running_replaces_the_stored_relations_rather_than_stacking(
    db_session: Session,
) -> None:
    user = User(is_guest=True)
    db_session.add(user)
    db_session.flush()

    older = _paper(db_session, slug="older", year=2011, openalex="W300")
    anchor = _paper(db_session, slug="anchor", year=2026, references=["W300"])
    db_session.add(SavedPaper(user_id=user.id, paper_id=older.id, reasons=["interesting"]))
    db_session.flush()

    relations_for(db_session, anchor, user.id)
    relations_for(db_session, anchor, user.id)
    db_session.flush()

    rows = list(
        db_session.query(PaperRelation).filter(PaperRelation.source_paper_id == anchor.id).all()
    )
    assert len(rows) == 1


@pytest.mark.integration
@requires_db
def test_a_relation_the_evidence_stops_supporting_is_removed(db_session: Session) -> None:
    # A stale relation is worse than none: the reader is told a paper is foundational on
    # evidence that is no longer there, and nothing on screen says it is out of date.
    user = User(is_guest=True)
    db_session.add(user)
    db_session.flush()

    older = _paper(db_session, slug="older", year=2011, openalex="W400")
    anchor = _paper(db_session, slug="anchor", year=2026, references=["W400"])
    db_session.add(SavedPaper(user_id=user.id, paper_id=older.id, reasons=["interesting"]))
    db_session.flush()

    relations_for(db_session, anchor, user.id)
    db_session.flush()

    anchor.raw_metadata = {"referenced_works": []}
    db_session.flush()
    relations_for(db_session, anchor, user.id)
    db_session.flush()

    assert (
        db_session.query(PaperRelation).filter(PaperRelation.source_paper_id == anchor.id).count()
        == 0
    )


@pytest.mark.integration
@requires_db
def test_the_pool_puts_the_readers_own_library_first(db_session: Session) -> None:
    user = User(is_guest=True)
    db_session.add(user)
    db_session.flush()

    stranger = _paper(db_session, slug="stranger", year=2026, field_id=None)
    mine = _paper(db_session, slug="mine", year=1999, field_id=None)
    anchor = _paper(db_session, slug="anchor", year=2026, field_id=None)
    db_session.add(SavedPaper(user_id=user.id, paper_id=mine.id, reasons=["interesting"]))
    db_session.flush()

    pool = candidate_pool(db_session, anchor, user.id)

    assert pool[0].canonical_id == "test:mine"
    assert stranger.id in {p.id for p in pool}


# ------------------------------------------------------------------ over HTTP


@pytest.mark.integration
@requires_db
def test_the_endpoint_answers_with_the_relation_and_its_evidence(
    client: TestClient, db_session: Session
) -> None:
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}

    _paper(db_session, slug="http-older", year=2011, openalex="W500")
    anchor = _paper(db_session, slug="http-anchor", year=2026, references=["W500"])
    db_session.commit()

    body = client.get(f"/papers/{anchor.id}/relations", headers=headers).json()

    assert [r["relationType"] for r in body["relations"]] == ["foundational"]
    relation = body["relations"][0]
    assert relation["basis"] == "citation"
    assert relation["evidence"]["citation"] == "anchor_cites_candidate"
    assert relation["paper"]["canonicalId"] == "test:http-older"


@pytest.mark.integration
@requires_db
def test_the_endpoint_returns_an_empty_list_rather_than_guessing(
    client: TestClient, db_session: Session
) -> None:
    # No citations, no mentions, nothing alike. "Nothing to show" is the honest answer, and
    # falling back to "papers that look similar" is precisely what section 17 forbids.
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}

    anchor = _paper(db_session, slug="http-lonely", year=2026)
    db_session.commit()

    body = client.get(f"/papers/{anchor.id}/relations", headers=headers).json()

    assert body["relations"] == []


@pytest.mark.integration
@requires_db
def test_the_endpoint_needs_a_reader(client: TestClient, db_session: Session) -> None:
    # The pool starts from the reader's own library, so there is no anonymous answer.
    anchor = _paper(db_session, slug="http-auth", year=2026)
    db_session.commit()

    assert client.get(f"/papers/{anchor.id}/relations").status_code == 401


@pytest.mark.integration
@requires_db
def test_an_unknown_paper_is_a_404(client: TestClient) -> None:
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}

    missing = "11111111-1111-4111-8111-111111111111"
    assert client.get(f"/papers/{missing}/relations", headers=headers).status_code == 404
