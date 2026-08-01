"""Feed construction (spec sections 6, 16, 30)."""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    Action,
    Impression,
    Interest,
    Paper,
    SavedPaper,
    User,
    UserSettings,
)
from papermatch_api.services import activity
from papermatch_api.services.feed import (
    NUDGE_ACTIONS,
    NUDGE_STRENGTH,
    POOL_ALLOCATION,
    FeedCursor,
    build_feed,
    feedback_nudges,
    mix_pattern,
    reason_text,
    reinjectable_paper_ids,
    significant_fields,
    suppressed_author_keys,
    suppressed_field_ids,
)
from papermatch_api.services.scoring import WEIGHTS
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture
def user(seeded_db: Session) -> User:
    row = User(is_guest=True)
    seeded_db.add(row)
    seeded_db.flush()
    seeded_db.add(UserSettings(user_id=row.id))
    seeded_db.flush()
    seeded_db.refresh(row)
    return row


def _set_interests(session: Session, user: User, field_ids: list[str]) -> None:
    for field_id in field_ids:
        session.add(Interest(user_id=user.id, field_id=field_id, strength=1.0, mode="main"))
    session.flush()
    session.refresh(user)


def _show(
    session: Session,
    user: User,
    paper: Paper,
    *,
    dwell_ms: int | None = None,
    shown_at: datetime | None = None,
) -> Impression:
    row = Impression(user_id=user.id, paper_id=paper.id, dwell_ms=dwell_ms)
    if shown_at is not None:
        row.shown_at = shown_at
    session.add(row)
    session.flush()
    return row


# ------------------------------------------------------------------------------- basics


def test_cursor_round_trips(seeded_db: Session) -> None:
    encoded = FeedCursor(seed=42, offset=20).encode()
    assert FeedCursor.decode(encoded) == FeedCursor(seed=42, offset=20)
    assert FeedCursor.decode(None) is None
    assert FeedCursor.decode("garbage") is None


def test_pool_allocation_sums_to_the_spec_mix() -> None:
    """Spec section 16: 70% 選択分野 / 20% 隣接分野 / 10% 未知."""
    assert POOL_ALLOCATION == {"matched": 0.70, "adjacent": 0.20, "exploration": 0.10}
    assert abs(sum(POOL_ALLOCATION.values()) - 1.0) < 1e-9
    assert mix_pattern() == [("matched", 7), ("adjacent", 2), ("exploration", 1)]


def test_feed_returns_cards_with_explainable_reasons(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th", "cs.LG"])
    page = build_feed(seeded_db, user, limit=10)

    assert len(page.items) == 10
    for item in page.items:
        assert item.reasons, "every card must say why it is here (spec section 6)"
        assert item.pool in {"matched", "adjacent", "exploration"}
        assert set(WEIGHTS) <= set(item.breakdown), "every scored term is accounted for"
        assert reason_text(item.reasons, "ja-JP")


def test_reasons_come_from_the_fixed_vocabulary_not_from_the_score(
    seeded_db: Session, user: User
) -> None:
    """The scorer names its own terms (`interest`, `freshness`); a card's reason is a
    sentence from `enums.json`. Leaking one vocabulary into the other would put an
    untranslated component name on a card."""
    _set_interests(seeded_db, user, ["hep-th", "cs.LG"])
    allowed = {"matches_field", "adjacent_field", "similar_to_saved", "recent", "foundational"}
    for item in build_feed(seeded_db, user, limit=10).items:
        assert set(item.reasons) <= allowed
        assert not set(item.reasons) & set(item.breakdown)


def test_reason_text_is_localised_and_short(seeded_db: Session) -> None:
    ja = reason_text(["matches_field", "recent"], "ja-JP")
    en = reason_text(["matches_field", "recent"], "en-US")
    assert ja and en and ja != en
    assert len(ja) < 60


# ----------------------------------------------------------------------- pool behaviour


def test_the_mix_is_seven_two_one_per_ten_cards(seeded_db: Session, user: User) -> None:
    """Spec section 16, with pools deep enough to actually hold the ratio."""
    # Two sibling fields: deep enough for the matched pool, while the other physics
    # siblings still supply the adjacent pool and maths/CS the exploration pool.
    _set_interests(seeded_db, user, ["hep-th", "cond-mat"])
    page = build_feed(seeded_db, user, limit=10)

    pools = [item.pool for item in page.items]
    assert pools.count("matched") == 7
    assert pools.count("adjacent") == 2
    assert pools.count("exploration") == 1

    for item in page.items:
        if item.pool != "matched":
            continue
        assert significant_fields(item.paper) & {"hep-th", "cond-mat"}


def test_an_exhausted_pool_gives_its_slots_away(seeded_db: Session, user: User) -> None:
    """A narrow interest must not produce a half-empty deck."""
    _set_interests(seeded_db, user, ["cs.CR"])
    page = build_feed(seeded_db, user, limit=20)

    matched = [i for i in page.items if i.pool == "matched"]
    assert len(page.items) == 20, "the page was not filled"
    assert len(matched) < 14, "this fixture cannot supply 70% from one narrow field"


def test_adjacent_and_exploration_pools_are_represented(seeded_db: Session, user: User) -> None:
    """Serendipity is not optional: a page of only chosen fields defeats the point."""
    _set_interests(seeded_db, user, ["hep-th"])
    page = build_feed(seeded_db, user, limit=20)
    pools = {item.pool for item in page.items}
    assert "matched" in pools
    assert pools & {"adjacent", "exploration"}, "no serendipity slots were filled"


def test_a_user_with_no_interests_still_gets_a_feed(seeded_db: Session, user: User) -> None:
    page = build_feed(seeded_db, user, limit=10)
    assert len(page.items) == 10
    assert all(item.pool == "exploration" for item in page.items)


# ------------------------------------------------------------------------- no repeats


def test_seen_papers_are_excluded(seeded_db: Session, user: User) -> None:
    """Spec section 16: 一度表示した論文は原則再表示しない."""
    _set_interests(seeded_db, user, ["hep-th", "math.AP"])
    first = build_feed(seeded_db, user, limit=10)
    for item in first.items:
        _show(seeded_db, user, item.paper)

    second = build_feed(seeded_db, user, limit=10)
    seen_ids = {item.paper.id for item in first.items}
    assert not seen_ids & {item.paper.id for item in second.items}


def test_saved_papers_do_not_come_back_to_discover(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["cs.LG"])
    page = build_feed(seeded_db, user, limit=5)
    target = page.items[0].paper
    activity.save_paper(seeded_db, user, target.id)

    again = build_feed(seeded_db, user, limit=20)
    assert target.id not in {item.paper.id for item in again.items}


def test_paging_within_a_snapshot_does_not_repeat_or_skip(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th", "cs.LG", "math.PR"])
    seen: list[uuid.UUID] = []
    cursor: str | None = None
    for _ in range(6):
        page = build_feed(seeded_db, user, limit=8, cursor=cursor)
        seen.extend(item.paper.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == len(set(seen)), "a card appeared on two pages of one snapshot"
    assert len(seen) >= 16


def test_the_same_cursor_returns_the_same_page(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th"])
    first = build_feed(seeded_db, user, limit=5)
    assert first.next_cursor is not None

    a = build_feed(seeded_db, user, limit=5, cursor=first.next_cursor)
    b = build_feed(seeded_db, user, limit=5, cursor=first.next_cursor)
    assert [i.paper.id for i in a.items] == [i.paper.id for i in b.items]


def test_withdrawn_papers_never_appear(seeded_db: Session, user: User) -> None:
    """Spec section 21: retraction state must be reflected."""
    paper = seeded_db.execute(select(Paper)).scalars().first()
    assert paper is not None
    paper.retraction_status = "withdrawn"
    seeded_db.flush()

    page = build_feed(seeded_db, user, limit=50)
    assert paper.id not in {item.paper.id for item in page.items}


# ------------------------------------------------------------------------- diversity


def test_consecutive_cards_avoid_repeating_the_same_field(seeded_db: Session, user: User) -> None:
    """Spec section 16: 同一テーマの連続抑制."""
    _set_interests(seeded_db, user, ["hep-th", "cs.LG", "math.PR", "quant-ph"])
    page = build_feed(seeded_db, user, limit=16)
    fields = [item.paper.primary_field_id for item in page.items]

    runs = sum(1 for a, b in itertools.pairwise(fields) if a == b and a is not None)
    # Some repetition is unavoidable when a pool is small; a majority would mean the
    # diversity pass is not running at all.
    assert runs <= len(fields) // 3, f"too many consecutive same-field cards: {fields}"


# ------------------------------------------------------------------------ suppression


def test_hiding_a_topic_removes_it_from_the_feed(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th", "cs.LG"])
    activity.record_action(
        seeded_db, user, action_type="hide_topic", paper_id=None, payload={"fieldId": "hep-th"}
    )

    assert suppressed_field_ids(seeded_db, user) == {"hep-th"}
    page = build_feed(seeded_db, user, limit=30)
    for item in page.items:
        # Suppression uses the same "what is this paper about" test as pool selection: an
        # incidental low-weight tag does not make a machine-learning paper a hep-th paper,
        # so hiding hep-th must not silently remove it.
        assert "hep-th" not in significant_fields(item.paper)


def test_undoing_a_hide_restores_the_topic(seeded_db: Session, user: User) -> None:
    """Suppression is derived from the action log, so undo needs no separate bookkeeping."""
    _set_interests(seeded_db, user, ["hep-th"])
    action = activity.record_action(
        seeded_db, user, action_type="hide_topic", paper_id=None, payload={"fieldId": "hep-th"}
    )
    assert suppressed_field_ids(seeded_db, user) == {"hep-th"}

    activity.undo_action(seeded_db, user, action.id)
    assert suppressed_field_ids(seeded_db, user) == set()


def test_hiding_an_author_removes_their_papers(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th", "cs.LG"])
    page = build_feed(seeded_db, user, limit=5)
    target = page.items[0].paper
    author_name = target.authors[0]["name"]

    activity.record_action(
        seeded_db,
        user,
        action_type="hide_author",
        paper_id=target.id,
        payload={"authorName": author_name},
    )
    assert suppressed_author_keys(seeded_db, user)

    again = build_feed(seeded_db, user, limit=50)
    assert target.id not in {item.paper.id for item in again.items}


def test_suppression_expires_after_the_window(seeded_db: Session, user: User) -> None:
    action = activity.record_action(
        seeded_db, user, action_type="hide_topic", paper_id=None, payload={"fieldId": "hep-th"}
    )
    action.created_at = datetime.now(tz=UTC) - timedelta(days=90)
    seeded_db.flush()
    assert suppressed_field_ids(seeded_db, user) == set()


# ---------------------------------------------------------------------- feed feedback


def _press(session: Session, user: User, action_type: str, times: int = 1) -> list[Action]:
    return [
        activity.record_action(session, user, action_type=action_type, paper_id=None, payload={})
        for _ in range(times)
    ]


def test_every_nudge_action_has_a_strength_or_is_the_documented_exception() -> None:
    """A fourth control added to `NUDGE_ACTIONS` without a strength would be counted,
    reported as a nudge, and then do nothing. `less_similar` is absent on purpose: it is a
    multiplier on a penalty the scorer already computed, not a flat addition."""
    assert set(NUDGE_STRENGTH) | {"less_similar"} == set(NUDGE_ACTIONS)


def test_an_untouched_feed_carries_no_nudge_terms(seeded_db: Session, user: User) -> None:
    """A reader who has pressed nothing must be scored exactly as before these existed."""
    _set_interests(seeded_db, user, ["hep-th", "cs.LG"])
    assert feedback_nudges(seeded_db, user) == {
        "less_similar": 0.0,
        "more_experimental": 0.0,
        "more_classic": 0.0,
    }
    for item in build_feed(seeded_db, user, limit=10).items:
        assert not set(item.breakdown) & set(NUDGE_ACTIONS)


def test_a_nudge_saturates_rather_than_accumulating(seeded_db: Session, user: User) -> None:
    """Section 16: 否定的フィードバックを「嫌い」と決めつけない. A control that could be
    pressed twenty times into a permanent ban would be exactly that."""
    _press(seeded_db, user, "more_classic", times=3)
    at_three = feedback_nudges(seeded_db, user)["more_classic"]
    _press(seeded_db, user, "more_classic", times=17)
    at_twenty = feedback_nudges(seeded_db, user)["more_classic"]

    assert at_three == at_twenty == 1.0


def test_asking_for_classic_papers_lifts_them(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th", "cs.LG"])
    # A fixed cursor pins the snapshot seed. Without it the two calls draw different
    # exploration jitter and every exploration card looks like the nudge moved it.
    frozen = FeedCursor(seed=7, offset=0).encode()
    before = {
        i.paper.id: i.score for i in build_feed(seeded_db, user, limit=60, cursor=frozen).items
    }

    _press(seeded_db, user, "more_classic", times=3)
    after = build_feed(seeded_db, user, limit=60, cursor=frozen).items

    lifted = [i for i in after if "more_classic" in i.breakdown]
    assert lifted, "expected some classic or old papers in the deck"
    for item in lifted:
        assert item.breakdown["more_classic"] > 0
        assert item.score > before[item.paper.id]
    # Everything else is left exactly where it was — a nudge lifts what was asked for, it
    # does not push down what was not.
    for item in after:
        if "more_classic" not in item.breakdown:
            assert item.score == pytest.approx(before[item.paper.id])


def test_asking_for_fewer_similar_papers_deepens_the_penalty(
    seeded_db: Session, user: User
) -> None:
    _set_interests(seeded_db, user, ["hep-th", "cs.LG"])
    shown = build_feed(seeded_db, user, limit=1).items[0].paper
    _show(seeded_db, user, shown)

    plain = {
        i.paper.id: i.breakdown["similarity_penalty"]
        for i in build_feed(seeded_db, user, limit=60).items
    }
    _press(seeded_db, user, "less_similar", times=3)
    nudged = build_feed(seeded_db, user, limit=60).items

    moved = [i for i in nudged if "less_similar" in i.breakdown]
    assert moved, "expected the penalty to be non-zero for something after showing a card"
    for item in moved:
        # A multiplier on the penalty already computed, so at full strength it doubles it.
        assert item.breakdown["less_similar"] < 0
        assert item.breakdown["less_similar"] == pytest.approx(plain[item.paper.id], abs=1e-4)

    # A paper resembling nothing the reader saw carries no term at all — there is nothing
    # there to suppress, and a flat penalty would punish every card for the sin of a few.
    untouched = [i for i in nudged if plain.get(i.paper.id) == 0.0]
    assert untouched
    assert all("less_similar" not in i.breakdown for i in untouched)


def test_undoing_a_nudge_removes_its_effect(seeded_db: Session, user: User) -> None:
    """Same mechanism as the suppressions: the query counts only actions not undone."""
    actions = _press(seeded_db, user, "more_experimental", times=2)
    assert feedback_nudges(seeded_db, user)["more_experimental"] > 0

    for action in actions:
        activity.undo_action(seeded_db, user, action.id)
    assert feedback_nudges(seeded_db, user)["more_experimental"] == 0.0


def test_a_nudge_expires_with_the_same_window_as_a_suppression(
    seeded_db: Session, user: User
) -> None:
    actions = _press(seeded_db, user, "more_experimental", times=3)
    for action in actions:
        action.created_at = datetime.now(tz=UTC) - timedelta(days=90)
    seeded_db.flush()
    assert feedback_nudges(seeded_db, user)["more_experimental"] == 0.0


def test_undoing_a_nudge_does_not_resurrect_the_card_it_was_sent_from(
    seeded_db: Session, user: User
) -> None:
    """実験系を増やす asks for a different mix, not for this paper back. Bringing a card the
    reader had already moved past back into the deck would be a change they did not ask for.
    """
    _set_interests(seeded_db, user, ["hep-th", "cs.LG"])
    card = build_feed(seeded_db, user, limit=1).items[0].paper
    _show(seeded_db, user, card)
    assert card.id not in {i.paper.id for i in build_feed(seeded_db, user, limit=60).items}

    action = activity.record_action(
        seeded_db, user, action_type="more_experimental", paper_id=card.id, payload={}
    )
    activity.undo_action(seeded_db, user, action.id)

    assert card.id not in {i.paper.id for i in build_feed(seeded_db, user, limit=60).items}


# ------------------------------------------------------------------------ re-injection


def test_a_skipped_card_returns_after_the_reshow_window(seeded_db: Session, user: User) -> None:
    """Spec section 16: 再投入条件 — 期間経過 + スキップのみ + 長時間閲覧なし."""
    _set_interests(seeded_db, user, ["hep-th"])
    page = build_feed(seeded_db, user, limit=1)
    target = page.items[0].paper

    long_ago = datetime.now(tz=UTC) - timedelta(days=user.settings.reshow_after_days + 1)
    _show(seeded_db, user, target, dwell_ms=1200, shown_at=long_ago)
    activity.record_action(seeded_db, user, action_type="skip", paper_id=target.id)

    assert target.id in reinjectable_paper_ids(seeded_db, user)
    again = build_feed(seeded_db, user, limit=50)
    assert target.id in {item.paper.id for item in again.items}


def test_a_recently_skipped_card_does_not_return(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th"])
    target = build_feed(seeded_db, user, limit=1).items[0].paper
    _show(seeded_db, user, target, dwell_ms=800)
    activity.record_action(seeded_db, user, action_type="skip", paper_id=target.id)

    assert reinjectable_paper_ids(seeded_db, user) == set()
    again = build_feed(seeded_db, user, limit=50)
    assert target.id not in {item.paper.id for item in again.items}


def test_a_card_that_was_read_is_never_re_injected(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th"])
    target = build_feed(seeded_db, user, limit=1).items[0].paper

    long_ago = datetime.now(tz=UTC) - timedelta(days=400)
    _show(seeded_db, user, target, dwell_ms=45_000, shown_at=long_ago)
    assert target.id not in reinjectable_paper_ids(seeded_db, user)


def test_a_card_that_was_translated_is_never_re_injected(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th"])
    target = build_feed(seeded_db, user, limit=1).items[0].paper

    long_ago = datetime.now(tz=UTC) - timedelta(days=400)
    _show(seeded_db, user, target, dwell_ms=500, shown_at=long_ago)
    activity.record_action(seeded_db, user, action_type="translate", paper_id=target.id)

    assert target.id not in reinjectable_paper_ids(seeded_db, user)


def test_reshow_disabled_means_never(seeded_db: Session, user: User) -> None:
    user.settings.reshow_after_days = 0
    seeded_db.flush()
    target = seeded_db.execute(select(Paper)).scalars().first()
    assert target is not None
    _show(seeded_db, user, target, shown_at=datetime.now(tz=UTC) - timedelta(days=9999))
    assert reinjectable_paper_ids(seeded_db, user) == set()


# ------------------------------------------------------------------------- difficulty


def test_math_level_zero_filters_out_formula_heavy_papers(seeded_db: Session, user: User) -> None:
    """Spec section 18, Level 0: 数式を表示しない."""
    _set_interests(seeded_db, user, ["hep-th", "cs.LG", "math.AP"])

    def difficulty_by_paper(level: str) -> dict[uuid.UUID, float]:
        user.settings.math_level = level
        seeded_db.flush()
        return {
            item.paper.id: item.breakdown["difficulty"]
            for item in build_feed(seeded_db, user, limit=50).items
            if item.paper.math_density > 0.5
        }

    # Compared against another level rather than against a fixed number: a threshold like
    # "< 0.6" keeps passing after a reweighting that stopped level 0 from meaning anything.
    tolerant = difficulty_by_paper("level_3")
    strict = difficulty_by_paper("level_0")

    assert strict, "expected formula-heavy papers to still be in the deck"
    # Level 0 zeroes the maths component of the fit score, so dense papers sink; they are
    # not hard-excluded, because a card is still better than an empty deck.
    assert all(strict[paper_id] < tolerant[paper_id] for paper_id in strict)


def test_saved_field_overlap_is_labelled(seeded_db: Session, user: User) -> None:
    _set_interests(seeded_db, user, ["hep-th"])
    first = build_feed(seeded_db, user, limit=1).items[0].paper
    seeded_db.add(SavedPaper(user_id=user.id, paper_id=first.id, reasons=["interesting"]))
    seeded_db.flush()

    page = build_feed(seeded_db, user, limit=30)
    same_field = [i for i in page.items if i.paper.primary_field_id == first.primary_field_id]
    assert same_field, "expected other papers in the same field"
    assert all("similar_to_saved" in i.reasons for i in same_field)


def test_degraded_flag_is_passed_through(seeded_db: Session, user: User) -> None:
    page = build_feed(seeded_db, user, limit=3, degraded=True)
    assert page.degraded is True


def test_actions_on_another_users_papers_do_not_leak(seeded_db: Session, user: User) -> None:
    other = User(is_guest=True)
    seeded_db.add(other)
    seeded_db.flush()
    seeded_db.add(UserSettings(user_id=other.id))
    seeded_db.flush()
    seeded_db.refresh(other)

    target = build_feed(seeded_db, other, limit=1).items[0].paper
    _show(seeded_db, other, target)
    seeded_db.add(
        Action(
            user_id=other.id,
            paper_id=target.id,
            action_type="hide_topic",
            payload={"fieldId": "hep-th"},
        )
    )
    seeded_db.flush()

    assert suppressed_field_ids(seeded_db, user) == set()
    page = build_feed(seeded_db, user, limit=50)
    assert target.id in {item.paper.id for item in page.items}
