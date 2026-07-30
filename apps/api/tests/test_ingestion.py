"""Integration tests: provider → database (spec section 30, 統合)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.models import AbstractSegment, AuditLog, Field, Paper, PaperIdentifier
from papermatch_api.providers.base import PaperQuery
from papermatch_api.providers.mock_paper import MockPaperProvider
from papermatch_api.services.ingestion import ingest, load_fields
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


def _count(session: Session, model: type) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


def test_fields_load_with_their_hierarchy(db_session: Session) -> None:
    load_fields(db_session, FIXTURES_DIR)
    roots = list(db_session.execute(select(Field).where(Field.parent_id.is_(None))).scalars())
    assert {r.id for r in roots} == {"physics", "math", "cs"}
    children = list(db_session.execute(select(Field).where(Field.parent_id == "physics")).scalars())
    assert {c.id for c in children} == {"hep-th", "cond-mat", "quant-ph", "astro-ph"}


def test_loading_fields_twice_does_not_duplicate_them(db_session: Session) -> None:
    load_fields(db_session, FIXTURES_DIR)
    first = _count(db_session, Field)
    load_fields(db_session, FIXTURES_DIR)
    assert _count(db_session, Field) == first


def test_ingestion_stores_papers_with_provenance(db_session: Session) -> None:
    load_fields(db_session, FIXTURES_DIR)
    report = ingest(db_session, MockPaperProvider(FIXTURES_DIR), query=PaperQuery(limit=100))

    assert report.inserted >= 40
    papers = list(db_session.execute(select(Paper)).scalars())
    for paper in papers:
        assert paper.source_provider
        assert paper.source_url
        assert paper.acquired_at is not None
        assert paper.abstract_redistributable is True, (
            "papers with unknown terms must not have been stored"
        )


def test_records_without_licence_terms_are_skipped_not_stored(db_session: Session) -> None:
    """Spec section 21: ライセンス不明の本文断片は扱わない."""
    load_fields(db_session, FIXTURES_DIR)
    report = ingest(db_session, MockPaperProvider(FIXTURES_DIR), query=PaperQuery(limit=100))
    assert report.skipped_unlicensed > 0
    stored = _count(db_session, Paper)
    assert stored == report.inserted
    assert stored + report.skipped_unlicensed == report.total_seen


def test_ingestion_is_idempotent(db_session: Session) -> None:
    """Spec section 25: 冪等な取り込みとジョブ."""
    load_fields(db_session, FIXTURES_DIR)
    provider = MockPaperProvider(FIXTURES_DIR)
    first = ingest(db_session, provider, query=PaperQuery(limit=100))
    papers_after_first = _count(db_session, Paper)
    identifiers_after_first = _count(db_session, PaperIdentifier)

    second = ingest(db_session, provider, query=PaperQuery(limit=100))

    assert _count(db_session, Paper) == papers_after_first
    assert _count(db_session, PaperIdentifier) == identifiers_after_first
    assert second.inserted == 0
    assert second.updated + second.merged_duplicates == first.inserted


def test_duplicate_variants_collapse_onto_the_existing_paper(db_session: Session) -> None:
    """Spec section 29: 同一DOI/arXivの重複カードが出ない."""
    load_fields(db_session, FIXTURES_DIR)
    ingest(db_session, MockPaperProvider(FIXTURES_DIR), query=PaperQuery(limit=100))
    baseline = _count(db_session, Paper)

    with_dupes = MockPaperProvider(FIXTURES_DIR, include_duplicate_variants=True)
    report = ingest(db_session, with_dupes, query=PaperQuery(limit=200))

    assert _count(db_session, Paper) == baseline, "duplicate variants created new rows"
    assert report.inserted == 0


def test_a_merged_paper_keeps_identifiers_from_every_source(db_session: Session) -> None:
    load_fields(db_session, FIXTURES_DIR)
    with_dupes = MockPaperProvider(FIXTURES_DIR, include_duplicate_variants=True)
    ingest(db_session, with_dupes, query=PaperQuery(limit=200))

    # The preprint/published pair: the surviving row must be reachable by both ids.
    rows = list(db_session.execute(select(PaperIdentifier)).scalars())
    by_paper: dict[str, set[str]] = {}
    for row in rows:
        by_paper.setdefault(str(row.paper_id), set()).add(row.kind)
    assert any({"doi", "arxiv"} <= kinds for kinds in by_paper.values())


def test_every_stored_identifier_points_at_exactly_one_paper(db_session: Session) -> None:
    load_fields(db_session, FIXTURES_DIR)
    with_dupes = MockPaperProvider(FIXTURES_DIR, include_duplicate_variants=True)
    ingest(db_session, with_dupes, query=PaperQuery(limit=200))

    duplicated = db_session.execute(
        select(PaperIdentifier.kind, PaperIdentifier.value, func.count())
        .group_by(PaperIdentifier.kind, PaperIdentifier.value)
        .having(func.count() > 1)
    ).all()
    assert duplicated == []


def test_abstract_structure_is_stored_as_offsets_not_edits(db_session: Session) -> None:
    """Spec section 8: AI分類の場合は自動検出ラベルを付け、原文を変更しない."""
    load_fields(db_session, FIXTURES_DIR)
    ingest(db_session, MockPaperProvider(FIXTURES_DIR), query=PaperQuery(limit=20))

    paper = db_session.execute(select(Paper)).scalars().first()
    assert paper is not None
    segments = list(
        db_session.execute(
            select(AbstractSegment).where(AbstractSegment.paper_id == paper.id)
        ).scalars()
    )
    assert len(segments) == 5
    assert {s.section for s in segments} == {
        "background",
        "problem",
        "method",
        "result",
        "significance",
    }
    for segment in segments:
        excerpt = paper.abstract[segment.start_offset : segment.end_offset]
        assert excerpt.strip(), "segment offsets must land inside the stored abstract"


def test_ingestion_writes_an_audit_entry(db_session: Session) -> None:
    """Spec section 0: 監査ログを省略しない."""
    load_fields(db_session, FIXTURES_DIR)
    ingest(db_session, MockPaperProvider(FIXTURES_DIR), query=PaperQuery(limit=10))

    entries = list(
        db_session.execute(select(AuditLog).where(AuditLog.kind == "ingestion")).scalars()
    )
    assert len(entries) == 1
    assert entries[0].actor == "provider:mock"
    assert "inserted" in entries[0].detail
    assert "skippedUnlicensed" in entries[0].detail


def test_field_weights_are_stored_for_canvas_colouring(db_session: Session) -> None:
    load_fields(db_session, FIXTURES_DIR)
    ingest(db_session, MockPaperProvider(FIXTURES_DIR), query=PaperQuery(limit=10))
    paper = db_session.execute(select(Paper)).scalars().first()
    assert paper is not None
    weights = {fw.field_id: fw.weight for fw in paper.field_weights}
    assert weights
    assert all(0.0 <= w <= 1.0 for w in weights.values())


def test_a_paper_without_source_structure_gets_a_heuristic_one(db_session: Session) -> None:
    """Spec section 8: every abstract gets structure, labelled with how it was found.

    Providers that publish structured abstracts are authoritative. Everything else — which
    is nearly all of arXiv — goes through the classifier, and the label says so.
    """
    from datetime import UTC, datetime

    from papermatch_api.providers.base import PaperRecord
    from papermatch_api.services.ingestion import upsert_record

    load_fields(db_session, FIXTURES_DIR)
    record = PaperRecord(
        canonical_id="arxiv:2501.00001",
        title="A Paper With No Published Structure",
        abstract=(
            "Expander graphs combine sparsity with strong connectivity. "
            "However, existing constructions cannot reach the required degree. "
            "We construct an explicit family using a zig-zag product. "
            "We obtain a spectral gap of 0.31 at degree eight. "
            "This suggests the construction extends to higher degrees."
        ),
        authors=({"name": "K. Aoki"},),
        year=2025,
        identifiers=({"kind": "arxiv", "value": "2501.00001"},),
        source_provider="arxiv",
        source_url="https://arxiv.org/abs/2501.00001",
        acquired_at=datetime.now(tz=UTC),
        license_id="CC-BY-4.0",
        license_url=None,
        abstract_redistributable=True,
        primary_field_id="math.CO",
        field_weights={"math.CO": 0.7, "math": 0.2},
    )

    paper, _ = upsert_record(db_session, record)
    segments = list(
        db_session.execute(
            select(AbstractSegment).where(AbstractSegment.paper_id == paper.id)
        ).scalars()
    )

    assert len(segments) == 5
    assert {s.detected_by for s in segments} == {"heuristic"}
    assert [s.section for s in sorted(segments, key=lambda s: s.start_offset)] == [
        "background",
        "problem",
        "method",
        "result",
        "significance",
    ]
    # A heuristic never claims certainty.
    assert all(s.confidence < 1.0 for s in segments)
    # And the abstract itself is untouched.
    assert paper.abstract == record.abstract


def test_source_supplied_structure_is_preferred_over_the_heuristic(
    db_session: Session,
) -> None:
    load_fields(db_session, FIXTURES_DIR)
    ingest(db_session, MockPaperProvider(FIXTURES_DIR), query=PaperQuery(limit=5))

    segments = list(db_session.execute(select(AbstractSegment)).scalars())
    assert segments
    assert {s.detected_by for s in segments} == {"source"}
