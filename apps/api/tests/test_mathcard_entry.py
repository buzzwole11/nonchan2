"""Two of section 10's maths-card entrances: the Discover offer and the Canvas tile.

Both were listed with 通知・推薦・Canvas 待ち; the recommendation stack and the Canvas now
exist, so they do too. What is worth pinning is the restraint — 低頻度 with an actual
memory, no slot taken from the 70/20/10, cards only from the reader's own library — because
each of those is a way this feature could quietly become an advertising channel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    Action,
    CanvasPosition,
    Equation,
    MathCard,
    Paper,
    SavedPaper,
    User,
)
from papermatch_api.passwords import hash_password
from papermatch_api.services import mathcard_feed
from papermatch_api.services.canvas import MATH_TILE_WEIGHT, layout_for
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]


def _user(session: Session, slug: str) -> User:
    row = User(
        email=f"{slug}@example.invalid",
        password_hash=hash_password("correct horse battery"),
        display_name=slug,
        is_guest=False,
    )
    session.add(row)
    session.flush()
    return row


def _paper(session: Session, slug: str) -> Paper:
    row = Paper(
        canonical_id=f"test:entry-{slug}",
        title=f"Paper {slug}",
        normalized_title=f"paper {slug}",
        abstract="An abstract about spectral gaps.",
        authors=[],
        year=2026,
        source_provider="mock",
        source_url=f"https://example.invalid/{slug}",
        acquired_at=datetime.now(tz=UTC),
    )
    session.add(row)
    session.flush()
    return row


def _card(session: Session, paper: Paper, title: str) -> MathCard:
    equation = Equation(
        paper_id=paper.id,
        latex=r"E = mc^2",
        display=True,
        provenance_kind="original",
        verification_status="source_exact",
        license_id="CC0-1.0",
        generation={},
    )
    session.add(equation)
    session.flush()
    card = MathCard(
        card_type="derivation",
        title=title,
        level="level_2",
        source_equation_ids=[str(equation.id)],
        review_status="draft",
        provenance_kind="ai_explanation",
        body="…",
    )
    session.add(card)
    session.flush()
    return card


def _save(session: Session, user: User, paper: Paper, days_ago: int) -> None:
    session.add(
        SavedPaper(
            user_id=user.id,
            paper_id=paper.id,
            saved_at=datetime.now(tz=UTC) - timedelta(days=days_ago),
        )
    )
    session.flush()


# ------------------------------------------------------------------ the Discover offer


def test_nothing_is_offered_to_a_reader_with_no_saved_papers(db_session: Session) -> None:
    # A card from a paper the reader never chose is an advertisement, not a re-encounter.
    user = _user(db_session, "empty")
    _card(db_session, _paper(db_session, "unsaved"), "Someone else's card")

    assert mathcard_feed.pick(db_session, user) is None


def test_the_offered_card_belongs_to_a_saved_paper(db_session: Session) -> None:
    user = _user(db_session, "saver")
    saved_paper = _paper(db_session, "saved")
    other_paper = _paper(db_session, "other")
    _save(db_session, user, saved_paper, days_ago=5)
    _card(db_session, other_paper, "Not this one")
    mine = _card(db_session, saved_paper, "This one")

    offered = mathcard_feed.pick(db_session, user)

    assert offered is not None
    assert offered.card.id == mine.id
    assert offered.paper.id == saved_paper.id


def test_the_longest_saved_paper_comes_first(db_session: Session) -> None:
    # The same instinct as section 9's resurfacing: the card is another way back into
    # something at risk of being forgotten.
    user = _user(db_session, "longest")
    old_paper, new_paper = _paper(db_session, "old"), _paper(db_session, "new")
    _save(db_session, user, old_paper, days_ago=30)
    _save(db_session, user, new_paper, days_ago=1)
    _card(db_session, new_paper, "New card")
    old_card = _card(db_session, old_paper, "Old card")

    offered = mathcard_feed.pick(db_session, user)

    assert offered is not None
    assert offered.card.id == old_card.id


def test_one_offer_keeps_the_feed_quiet_for_a_week(db_session: Session) -> None:
    """低頻度 is a memory, not an adjective.

    The cooldown binds whether or not the reader opened the card: ignoring the invitation
    is an answer, and repeating it next session is the app insisting.
    """
    user = _user(db_session, "quiet")
    paper = _paper(db_session, "quiet-paper")
    _save(db_session, user, paper, days_ago=10)
    _card(db_session, paper, "Card")

    first = mathcard_feed.pick(db_session, user)
    assert first is not None
    mathcard_feed.record(db_session, user, first)

    assert mathcard_feed.pick(db_session, user) is None


def test_the_offer_is_in_the_audit_trail_like_everything_else(db_session: Session) -> None:
    user = _user(db_session, "audited")
    paper = _paper(db_session, "audited-paper")
    _save(db_session, user, paper, days_ago=10)
    _card(db_session, paper, "Card")

    offered = mathcard_feed.pick(db_session, user)
    assert offered is not None
    mathcard_feed.record(db_session, user, offered)

    row = db_session.execute(
        select(Action).where(Action.user_id == user.id, Action.action_type == "mathcard_teaser")
    ).scalar_one()
    assert row.paper_id == paper.id
    assert row.payload["mathCardId"] == str(offered.card.id)


def test_the_feed_endpoint_carries_the_offer_beside_the_items(client, seeded_db: Session) -> None:  # type: ignore[no-untyped-def]
    # Beside, not inside: the 70/20/10 is for paper discovery (section 16), and the maths
    # card must not spend one of its slots.
    auth = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {auth.json()['accessToken']}"}
    me = client.get("/me", headers=headers).json()
    user = seeded_db.get(User, uuid.UUID(me["id"]))
    assert user is not None

    # A saved paper with a maths card, alongside the seeded corpus the feed draws from.
    paper = _paper(seeded_db, "feed-offer")
    _save(seeded_db, user, paper, days_ago=10)
    card = _card(seeded_db, paper, "Feed offer card")

    body = client.get("/feed", headers=headers).json()

    assert body["mathCard"] is not None
    assert body["mathCard"]["cardId"] == str(card.id)
    assert body["mathCard"]["paperTitle"] == paper.title
    assert body["mathCard"]["provenanceKind"] == "ai_explanation"
    # The paper items themselves are untouched by the offer.
    assert all("paper" in item for item in body["items"])


# ------------------------------------------------------------------ the Canvas tile


def test_a_saved_paper_with_a_card_grows_a_small_tile_beside_it(db_session: Session) -> None:
    user = _user(db_session, "canvas")
    paper = _paper(db_session, "canvas-paper")
    _save(db_session, user, paper, days_ago=3)
    card = _card(db_session, paper, "Canvas card")

    tiles = layout_for(db_session, user)

    card_tiles = [tile for tile in tiles if tile.entity_type == "math_card"]
    assert [tile.entity_id for tile in card_tiles] == [card.id]
    assert card_tiles[0].anchor_paper_id == paper.id
    # Small and fixed: the size means "there is maths here", not "this is important".
    assert card_tiles[0].weight == MATH_TILE_WEIGHT
    # Beside its paper, in the paper's cluster.
    paper_tile = next(tile for tile in tiles if tile.entity_id == paper.id)
    assert card_tiles[0].cluster_id == paper_tile.cluster_id


def test_a_card_on_an_unsaved_paper_gets_no_tile(db_session: Session) -> None:
    # The Canvas is the reader's own library arranged in space (section 13), and a tile
    # for something they never chose would make it a catalogue.
    user = _user(db_session, "catalogue")
    saved_paper, other = _paper(db_session, "cat-saved"), _paper(db_session, "cat-other")
    _save(db_session, user, saved_paper, days_ago=3)
    _card(db_session, other, "Stranger's card")

    tiles = layout_for(db_session, user)

    assert [tile for tile in tiles if tile.entity_type == "math_card"] == []


def test_the_card_tile_keeps_its_place_between_visits(db_session: Session) -> None:
    # The plane must not rearrange itself while the reader is away — the same contract as
    # paper tiles, so it is stored in the same table.
    user = _user(db_session, "stable")
    paper = _paper(db_session, "stable-paper")
    _save(db_session, user, paper, days_ago=3)
    card = _card(db_session, paper, "Stable card")

    first = layout_for(db_session, user)
    second = layout_for(db_session, user)

    def coords(tiles):  # type: ignore[no-untyped-def]
        return {(t.entity_id, t.x, t.y) for t in tiles if t.entity_type == "math_card"}

    assert coords(first) == coords(second)
    stored = db_session.execute(
        select(CanvasPosition).where(
            CanvasPosition.entity_type == "math_card", CanvasPosition.entity_id == card.id
        )
    ).scalar_one()
    assert stored.user_id == user.id


def test_the_canvas_endpoint_serialises_the_card_with_its_anchor_paper(
    client, seeded_db: Session
) -> None:  # type: ignore[no-untyped-def]
    auth = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {auth.json()['accessToken']}"}
    me = client.get("/me", headers=headers).json()
    user = seeded_db.get(User, uuid.UUID(me["id"]))
    assert user is not None

    paper = _paper(seeded_db, "canvas-endpoint")
    _save(seeded_db, user, paper, days_ago=2)
    card = _card(seeded_db, paper, "Canvas endpoint card")

    body = client.get("/canvas", headers=headers).json()

    card_tiles = [t for t in body["tiles"] if t["entityType"] == "math_card"]
    assert card_tiles
    tile = card_tiles[0]
    # The anchoring paper travels with the tile: colour and cluster come from the reader's
    # own library, and the client can say which saved paper the maths belongs to.
    assert tile["paper"]["id"] == str(paper.id)
    assert tile["mathCard"]["cardId"] == str(card.id)
    assert tile["mathCard"]["provenanceKind"] == "ai_explanation"
