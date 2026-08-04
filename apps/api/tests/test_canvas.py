"""Canvas placement (spec section 13).

The interesting assertions are all about *not moving*. Section 13 asks for a plane a
reader can come back to and recognise, and the whole design — a data-independent
projection, a grid that is claimed rather than repacked — exists to make that structural
rather than something re-run and hoped for.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import CanvasPosition, Paper, SavedPaper, User
from papermatch_api.services.canvas import (
    LAYOUT_VERSION,
    field_anchor,
    layout_for,
    move_tile,
    personal_weight,
    project,
    tile_size,
)
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture
def reader(seeded_db: Session) -> User:
    row = User(is_guest=True)
    seeded_db.add(row)
    seeded_db.flush()
    return row


def _save(session: Session, user: User, papers: list[Paper]) -> None:
    for paper in papers:
        session.add(
            SavedPaper(user_id=user.id, paper_id=paper.id, reasons=["interesting"], status="unread")
        )
    session.flush()


def _papers(session: Session, count: int, *, skip: int = 0) -> list[Paper]:
    return list(session.execute(select(Paper).offset(skip).limit(count)).scalars())


# ------------------------------------------------------------------ stability


def test_adding_a_paper_moves_nothing(seeded_db: Session, reader: User) -> None:
    """The requirement that rules out t-SNE and UMAP.

    Both depend on the whole input set, so one new paper rearranges every tile. A canvas
    whose tiles wander is not a place.
    """
    _save(seeded_db, reader, _papers(seeded_db, 10))
    before = {tile.entity_id: (tile.x, tile.y) for tile in layout_for(seeded_db, reader)}

    _save(seeded_db, reader, _papers(seeded_db, 5, skip=10))
    after = {tile.entity_id: (tile.x, tile.y) for tile in layout_for(seeded_db, reader)}

    for entity_id, position in before.items():
        assert after[entity_id] == position


def test_running_the_layout_twice_changes_nothing(seeded_db: Session, reader: User) -> None:
    _save(seeded_db, reader, _papers(seeded_db, 8))

    first = [(tile.entity_id, tile.x, tile.y) for tile in layout_for(seeded_db, reader)]
    second = [(tile.entity_id, tile.x, tile.y) for tile in layout_for(seeded_db, reader)]

    assert first == second


def test_the_projection_depends_only_on_the_vector() -> None:
    # No corpus, no fitting, no random state: the same vector projects to the same point
    # on every device and in every run.
    vector = [0.1 * ((index % 7) - 3) for index in range(512)]

    assert project(vector) == project(list(vector))


def test_a_field_anchor_is_the_same_every_time() -> None:
    assert field_anchor("math.PR") == field_anchor("math.PR")
    assert field_anchor("math.PR") != field_anchor("hep-th")


def test_papers_with_no_field_share_one_anchor() -> None:
    """ "We do not know" is one place, not a hundred scattered ones."""
    assert field_anchor(None) == field_anchor(None)


def test_every_position_records_the_layout_version(seeded_db: Session, reader: User) -> None:
    # Section 13: 配置アルゴリズムの版を保持, so a re-layout can be told from its predecessor
    # and rolled back.
    _save(seeded_db, reader, _papers(seeded_db, 3))
    layout_for(seeded_db, reader)

    rows = list(
        seeded_db.execute(
            select(CanvasPosition).where(CanvasPosition.user_id == reader.id)
        ).scalars()
    )
    assert rows
    assert all(row.layout_version == LAYOUT_VERSION for row in rows)


# ------------------------------------------------------------------ the mosaic


def test_no_two_tiles_share_a_cell(seeded_db: Session, reader: User) -> None:
    _save(seeded_db, reader, _papers(seeded_db, 30))

    tiles = layout_for(seeded_db, reader)

    assert len({(tile.x, tile.y) for tile in tiles}) == len(tiles)


def test_papers_in_the_same_field_land_near_each_other(seeded_db: Session, reader: User) -> None:
    """The island *is* the field; a tile in the wrong one is the worse lie."""
    _save(seeded_db, reader, _papers(seeded_db, 40))
    tiles = layout_for(seeded_db, reader)

    grouped: dict[str, list[tuple[float, float]]] = {}
    for tile in tiles:
        if tile.cluster_id is not None:
            grouped.setdefault(tile.cluster_id, []).append((tile.x, tile.y))

    crowded = [points for points in grouped.values() if len(points) >= 2]
    assert crowded, "the sample corpus should have at least one field with two saved papers"

    for points in crowded:
        anchor_x, anchor_y = 0.0, 0.0
        for x, y in points:
            anchor_x += x / len(points)
            anchor_y += y / len(points)
        for x, y in points:
            # Well inside the island: the spread is 7 units and cells are 1 apart.
            assert math.dist((x, y), (anchor_x, anchor_y)) < 20.0


def test_a_tile_is_placed_even_with_no_embedding(seeded_db: Session, reader: User) -> None:
    # A paper whose vector never got stored still belongs on the plane; it lands at its
    # field's anchor rather than vanishing.
    paper = Paper(
        canonical_id="test:no-embedding",
        title="No Vector",
        normalized_title="no vector",
        abstract="x",
        authors=[],
        year=2024,
        source_provider="mock",
        source_url="https://example.invalid/x",
        acquired_at=datetime.now(tz=UTC),
    )
    seeded_db.add(paper)
    seeded_db.flush()
    _save(seeded_db, reader, [paper])

    tiles = layout_for(seeded_db, reader)

    assert any(tile.entity_id == paper.id for tile in tiles)


def test_an_empty_library_produces_no_tiles(seeded_db: Session, reader: User) -> None:
    assert layout_for(seeded_db, reader) == []


# ------------------------------------------------------------------ manual placement


def test_a_moved_tile_stays_where_the_reader_put_it(seeded_db: Session, reader: User) -> None:
    """Section 13: 手動配置を尊重.

    A re-layout that quietly undid the reader's arrangement would make the plane
    untrustworthy in exactly the way section 13 is trying to prevent.
    """
    papers = _papers(seeded_db, 5)
    _save(seeded_db, reader, papers)
    layout_for(seeded_db, reader)

    move_tile(seeded_db, reader, papers[0].id, x=100.0, y=-100.0)
    _save(seeded_db, reader, _papers(seeded_db, 5, skip=5))
    tiles = {tile.entity_id: tile for tile in layout_for(seeded_db, reader)}

    assert (tiles[papers[0].id].x, tiles[papers[0].id].y) == (100.0, -100.0)
    assert tiles[papers[0].id].user_override is True


def test_moving_a_tile_that_was_never_placed_still_records_it(
    seeded_db: Session, reader: User
) -> None:
    paper = _papers(seeded_db, 1)[0]
    _save(seeded_db, reader, [paper])

    position = move_tile(seeded_db, reader, paper.id, x=3.0, y=4.0)

    assert position.user_override is True
    assert (position.x, position.y) == (3.0, 4.0)


# ------------------------------------------------------------------ size


def test_weight_grows_with_attention_but_is_compressed(seeded_db: Session, reader: User) -> None:
    """Section 13: サイズは対数圧縮.

    Without it, one paper opened forty times is the size of a field island.
    """
    paper = _papers(seeded_db, 1)[0]
    saved = SavedPaper(
        user_id=reader.id, paper_id=paper.id, reasons=["interesting"], status="unread", priority=0
    )
    seeded_db.add(saved)
    seeded_db.flush()

    quiet = personal_weight(saved)
    busy = personal_weight(saved, visits=40)

    assert 0.0 < quiet < busy <= 1.0
    # Forty times the attention is nowhere near forty times the weight.
    assert busy < quiet * 6


def test_weight_never_leaves_the_unit_interval(seeded_db: Session, reader: User) -> None:
    paper = _papers(seeded_db, 1)[0]
    saved = SavedPaper(
        user_id=reader.id, paper_id=paper.id, reasons=["interesting"], status="unread", priority=99
    )
    seeded_db.add(saved)
    seeded_db.flush()

    assert 0.0 <= personal_weight(saved, visits=10_000) <= 1.0


def test_tile_size_is_bounded_at_both_ends() -> None:
    assert tile_size(0.0) == pytest.approx(0.6)
    assert tile_size(1.0) == pytest.approx(1.6)
    assert tile_size(-5.0) == pytest.approx(0.6)
    assert tile_size(5.0) == pytest.approx(1.6)
