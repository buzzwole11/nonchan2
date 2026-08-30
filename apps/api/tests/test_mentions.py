"""Storing bodies, and turning them into relations (spec sections 17, 21).

Two things are under test and they are the two halves of the same rule. Storage is the
licence gate applied to a table: a row in `paper_full_texts` is a statement that we were
allowed to keep this text, so the tests are mostly about rows that must *not* exist.
Extraction is the other half: `contrasting` is the one label that needs a sentence somebody
actually wrote, and this is where that sentence comes from.

The fixture corpus is what makes the second half testable at all. `fixtures/fulltext/
citing.tex` is keyed to a paper that exists in `papers.sample.json` and every paper it refers
to is in that corpus too — so these tests run the real path from a seeded database rather
than from hand-built objects that agree with the code by construction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import AuditLog, Paper, PaperFullText
from papermatch_api.providers.base import FullTextRecord
from papermatch_api.providers.mock_fulltext import MockFullTextProvider
from papermatch_api.services.fulltext import load_full_texts, store_full_text, stored_body
from papermatch_api.services.mentions import mentions_for, paper_key
from papermatch_api.services.relations import candidates_for, classify_all
from tests.conftest import FIXTURES_DIR, requires_db

pytestmark = [pytest.mark.integration, requires_db]

#: The citing fixture, and the three corpus papers it refers to.
CITING = "arxiv:2604.14247"
BY_IDENTIFIER = "doi:10.4171/pm.2026.0007"  # Concentration for Non-Reversible Measures
BY_AUTHOR_YEAR = "arxiv:2607.10685"  # Thresholds for Sparse Subgraphs — the contrast
BY_TITLE = "arxiv:2501.13973"  # Improved Bounds for Off-Diagonal Ramsey Numbers


def _record(**overrides: object) -> FullTextRecord:
    defaults: dict[str, object] = {
        "canonical_id": "arXiv:2601.00001",
        "body_format": "latex",
        "body": r"\begin{document}A body.\end{document}",
        "license_id": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_url": "https://example.invalid/abs/2601.00001",
        "retrieved_at": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    return FullTextRecord(**defaults)  # type: ignore[arg-type]


def _paper(session: Session, slug: str) -> Paper:
    row = Paper(
        canonical_id=f"test:body-{slug}",
        title=f"Paper {slug}",
        normalized_title=f"paper {slug}",
        abstract="An abstract.",
        authors=[],
        year=2026,
        source_provider="mock",
        source_url=f"https://example.invalid/{slug}",
        acquired_at=datetime.now(tz=UTC),
    )
    session.add(row)
    session.flush()
    return row


def _by_canonical_id(session: Session, canonical_id: str) -> Paper:
    paper = session.execute(
        select(Paper).where(Paper.canonical_id == canonical_id)
    ).scalar_one_or_none()
    assert paper is not None, f"the sample corpus no longer contains {canonical_id}"
    return paper


# ------------------------------------------------------------------ storing a body


def test_a_permitted_body_is_kept_with_the_licence_that_permitted_it(db_session: Session) -> None:
    paper = _paper(db_session, "permitted")

    row = store_full_text(db_session, paper, _record())

    assert row is not None
    # The licence of the *body*. Storing the paper's metadata licence here is the mistake
    # the gate exists to prevent, and this column is where it would show up.
    assert row.license_id == "CC-BY-4.0"
    assert stored_body(db_session, paper.id) == _record().body


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"license_id": None}, "unknown licence"),
        ({"license_id": "arXiv-1.0"}, "refused licence"),
        ({"license_id": "SomeLicence-9.9"}, "unrecognised licence"),
        ({"source_url": ""}, "no link to cite"),
        ({"body": "   "}, "empty body"),
        ({"body_format": "pdf"}, "unsupported format"),
    ],
)
def test_a_refused_body_leaves_no_row_at_all(
    db_session: Session, overrides: dict[str, object], why: str
) -> None:
    # No row rather than a row flagged as unusable: the row's existence is the permission,
    # and a flag is something a later query can forget to check.
    paper = _paper(db_session, f"refused-{abs(hash(why))}")

    assert store_full_text(db_session, paper, _record(**overrides)) is None
    assert db_session.get(PaperFullText, paper.id) is None


def test_nothing_from_the_provider_leaves_no_row(db_session: Session) -> None:
    paper = _paper(db_session, "absent")

    assert store_full_text(db_session, paper, None) is None
    assert stored_body(db_session, paper.id) is None


def test_a_licence_that_stops_permitting_removes_the_body_already_stored(
    db_session: Session,
) -> None:
    """The case that would otherwise leave a body behind that we may no longer keep.

    A paper is republished, or a manifest is corrected, and the licence goes from permissive
    to unknown. Keeping the old row would mean the gate had been passed once and never again.
    """
    paper = _paper(db_session, "revoked")
    assert store_full_text(db_session, paper, _record()) is not None

    assert store_full_text(db_session, paper, _record(license_id=None)) is None
    assert db_session.get(PaperFullText, paper.id) is None


def test_re_storing_replaces_the_body_rather_than_adding_a_second(db_session: Session) -> None:
    # One body per paper: two rows would be two answers to "what does this paper say".
    paper = _paper(db_session, "replaced")
    store_full_text(db_session, paper, _record())

    store_full_text(db_session, paper, _record(body=r"\begin{document}Revised.\end{document}"))

    rows = db_session.execute(
        select(PaperFullText).where(PaperFullText.paper_id == paper.id)
    ).scalars()
    assert [r.body for r in rows] == [r"\begin{document}Revised.\end{document}"]


# ------------------------------------------------------------------ the pass over the corpus


def test_the_corpus_pass_stores_the_citing_fixture_and_refuses_the_rest(
    seeded_db: Session,
) -> None:
    report = load_full_texts(seeded_db, MockFullTextProvider(Path(FIXTURES_DIR)))

    # Only one manifest entry is keyed to a paper in this corpus; the others exist to
    # exercise the gate and have no paper to attach to.
    assert report.stored == 1
    assert stored_body(seeded_db, _by_canonical_id(seeded_db, CITING).id) is not None


def test_every_licence_decision_is_written_to_the_audit_log(seeded_db: Session) -> None:
    load_full_texts(seeded_db, MockFullTextProvider(Path(FIXTURES_DIR)))

    entries = list(
        seeded_db.execute(
            select(AuditLog).where(AuditLog.kind == "fulltext.licence_decision")
        ).scalars()
    )

    # Section 21 requires the decision to be answerable later. A body that is simply missing
    # from the table cannot say whether it was never offered or was offered and declined.
    assert entries
    for entry in entries:
        assert entry.detail["reason"]
        assert entry.detail["code"]


# ------------------------------------------------------------------ mentions from real text


def test_the_citing_paper_mentions_exactly_the_papers_it_refers_to(seeded_db: Session) -> None:
    load_full_texts(seeded_db, MockFullTextProvider(Path(FIXTURES_DIR)))
    anchor = _by_canonical_id(seeded_db, CITING)
    pool = list(seeded_db.execute(select(Paper).where(Paper.id != anchor.id)).scalars())

    found = mentions_for(seeded_db, anchor, pool)

    named = {str(paper_id) for paper_id in found}
    expected = {
        str(_by_canonical_id(seeded_db, canonical_id).id)
        for canonical_id in (BY_IDENTIFIER, BY_AUTHOR_YEAR, BY_TITLE)
    }
    # Exactly these. A fourth would mean the extractor matched something on prose alone,
    # which is the failure that turns into a wrong claim about mathematics.
    assert named == expected


def test_a_mention_records_whose_text_the_sentence_came_from(seeded_db: Session) -> None:
    # "This paper says it disagrees with that one" and the reverse are different statements
    # about the literature, and the UI attributes the sentence to one of them.
    load_full_texts(seeded_db, MockFullTextProvider(Path(FIXTURES_DIR)))
    anchor = _by_canonical_id(seeded_db, CITING)
    other = _by_canonical_id(seeded_db, BY_AUTHOR_YEAR)

    found = mentions_for(seeded_db, anchor, [other])

    assert [m.source for m in found[other.id]] == [str(anchor.id)]


def test_a_paper_with_no_stored_body_produces_no_mentions(seeded_db: Session) -> None:
    # Most papers have no body, and an empty mention list must not read as "these papers do
    # not refer to each other".
    anchor = _by_canonical_id(seeded_db, BY_TITLE)
    pool = list(seeded_db.execute(select(Paper).where(Paper.id != anchor.id)).scalars())

    assert mentions_for(seeded_db, anchor, pool) == {}


def test_the_surname_rule_reads_the_last_name_from_the_author_record(
    seeded_db: Session,
) -> None:
    key = paper_key(_by_canonical_id(seeded_db, BY_AUTHOR_YEAR))

    assert key.surnames == ("almeida",)
    assert key.year == 2026


# ------------------------------------------------------------------ what the labels become


def test_a_contrastive_sentence_produces_contrasting_end_to_end(seeded_db: Session) -> None:
    """The label section 17 could not previously reach from real data.

    Nothing here is hand-built: the sentence comes out of a stored LaTeX body, the reference
    is resolved against the corpus, and `classify` sees the same `Mention` it would see in a
    request. Before the body was stored anywhere, this path had no input and `contrasting`
    was unreachable outside unit tests.
    """
    load_full_texts(seeded_db, MockFullTextProvider(Path(FIXTURES_DIR)))
    anchor = _by_canonical_id(seeded_db, CITING)
    contrasted = _by_canonical_id(seeded_db, BY_AUTHOR_YEAR)
    pool = [contrasted]

    found = mentions_for(seeded_db, anchor, pool)
    classified = dict(classify_all(anchor.year, candidates_for(seeded_db, anchor, pool, found)))

    relation = classified[str(contrasted.id)]
    assert relation.relation_type == "contrasting"
    assert relation.evidence["contrastCue"] == "in contrast"
    assert relation.evidence["mention"]["snippet"].startswith("In contrast to Almeida (2026)")


def test_a_plain_reference_is_related_and_not_contrasting(seeded_db: Session) -> None:
    # A mention with no contrastive cue is a real connection and a weaker claim. Reporting
    # it as `contrasting` would tell the reader the papers disagree on the strength of a
    # sentence that says only that one cites the other.
    load_full_texts(seeded_db, MockFullTextProvider(Path(FIXTURES_DIR)))
    anchor = _by_canonical_id(seeded_db, CITING)
    cited = _by_canonical_id(seeded_db, BY_IDENTIFIER)
    pool = [cited]

    found = mentions_for(seeded_db, anchor, pool)
    classified = dict(classify_all(anchor.year, candidates_for(seeded_db, anchor, pool, found)))

    assert classified[str(cited.id)].relation_type != "contrasting"
