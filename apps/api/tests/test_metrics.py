"""Section 27's numbers.

Most of the ways this can be wrong are quiet: a rate over an empty denominator that prints
0.000, a metric nobody can compute that is simply absent, a guardrail that looks at the
wrong half of the data and reads zero. Each of those produces a report that looks fine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    Action,
    ContentReport,
    Impression,
    MathCard,
    Paper,
    User,
    UserSettings,
)
from papermatch_api.services.math_content import load_math_cards
from papermatch_api.services.metrics import MEANINGFUL_DWELL_MS, SESSION_GAP, collect
from tests.conftest import FIXTURES_DIR, requires_db

pytestmark = [pytest.mark.integration, requires_db]

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


@pytest.fixture
def user(seeded_db: Session) -> User:
    row = User(is_guest=True)
    seeded_db.add(row)
    seeded_db.flush()
    seeded_db.add(UserSettings(user_id=row.id))
    seeded_db.flush()
    return row


def _papers(session: Session, count: int) -> list[Paper]:
    return list(session.execute(select(Paper).limit(count)).scalars())


def _shown(session: Session, user: User, paper: Paper, *, at: datetime, dwell: int | None) -> None:
    session.add(
        Impression(user_id=user.id, paper_id=paper.id, shown_at=at, dwell_ms=dwell, position=0)
    )
    session.flush()


def _acted(session: Session, user: User, paper: Paper, kind: str, *, at: datetime) -> None:
    session.add(
        Action(user_id=user.id, paper_id=paper.id, action_type=kind, payload={}, created_at=at)
    )
    session.flush()


def _metric(session: Session, key: str, **kwargs: object):  # type: ignore[no-untyped-def]
    report = collect(session, now=NOW, **kwargs)  # type: ignore[arg-type]
    found = next((m for m in report.metrics if m.key == key), None)
    assert found is not None, f"{key} is missing from the report entirely"
    return found


# --------------------------------------------------------------- absent, not zero


def test_a_rate_with_nothing_to_divide_by_is_absent_rather_than_zero(
    seeded_db: Session, user: User
) -> None:
    """0.000 reads as "nobody does this". The truth is "nobody has had the chance yet"."""
    assert _metric(seeded_db, "save.rate").value is None


def test_metrics_nothing_can_compute_are_listed_rather_than_dropped(
    seeded_db: Session, user: User
) -> None:
    """A report of twelve numbers looks complete. The point of this module is to show where
    the app is blind, so an absent metric has to appear *as* absent."""
    report = collect(seeded_db, now=NOW)
    keys = {m.key for m in report.uncomputable}

    assert "math_card.completion_rate" in keys, "nothing records finishing a maths card"
    assert "canvas.to_paper_rate" in keys, "Canvas does not exist yet"
    assert "guard.crash_and_gesture_failure" in keys, "there is no client telemetry"
    for metric in report.uncomputable:
        assert metric.detail, "an absent metric has to say what is missing"


def test_the_rendered_report_says_how_many_it_could_not_compute(
    seeded_db: Session, user: User
) -> None:
    rendered = collect(seeded_db, now=NOW).render()
    assert "cannot be computed" in rendered
    assert "—" in rendered


# ------------------------------------------------------------------- denominators


def test_the_ten_second_share_ignores_impressions_with_no_dwell_recorded(
    seeded_db: Session, user: User
) -> None:
    """Over *all* impressions, this number falls whenever the client fails to report a
    dwell — exactly when it should not move."""
    a, b, c = _papers(seeded_db, 3)
    _shown(seeded_db, user, a, at=NOW - timedelta(minutes=5), dwell=MEANINGFUL_DWELL_MS + 1)
    _shown(seeded_db, user, b, at=NOW - timedelta(minutes=4), dwell=500)
    _shown(seeded_db, user, c, at=NOW - timedelta(minutes=3), dwell=None)

    # One of the two measured, not one of the three seen.
    assert _metric(seeded_db, "read.ten_second_share").value == pytest.approx(0.5)


def test_the_undo_rate_is_over_the_actions_that_can_be_undone(
    seeded_db: Session, user: User
) -> None:
    a, b = _papers(seeded_db, 2)
    _acted(seeded_db, user, a, "save", at=NOW - timedelta(minutes=5))
    _acted(seeded_db, user, b, "skip", at=NOW - timedelta(minutes=4))
    _acted(seeded_db, user, a, "undo", at=NOW - timedelta(minutes=3))

    assert _metric(seeded_db, "undo.rate").value == pytest.approx(0.5)


# --------------------------------------------------------------------- North Star


def test_reading_without_acting_is_not_a_meaningful_session(seeded_db: Session, user: User) -> None:
    paper = _papers(seeded_db, 1)[0]
    _shown(seeded_db, user, paper, at=NOW - timedelta(minutes=5), dwell=MEANINGFUL_DWELL_MS)

    assert _metric(seeded_db, "north_star.meaningful_sessions").value == 0


def test_acting_without_reading_is_not_a_meaningful_session(seeded_db: Session, user: User) -> None:
    """A save after a two-second glance is not 原文の一部を自力で読み."""
    paper = _papers(seeded_db, 1)[0]
    _shown(seeded_db, user, paper, at=NOW - timedelta(minutes=5), dwell=800)
    _acted(seeded_db, user, paper, "save", at=NOW - timedelta(minutes=5))

    assert _metric(seeded_db, "north_star.meaningful_sessions").value == 0


def test_reading_then_saving_counts_once(seeded_db: Session, user: User) -> None:
    a, b = _papers(seeded_db, 2)
    _shown(seeded_db, user, a, at=NOW - timedelta(minutes=6), dwell=MEANINGFUL_DWELL_MS)
    _shown(seeded_db, user, b, at=NOW - timedelta(minutes=5), dwell=MEANINGFUL_DWELL_MS)
    _acted(seeded_db, user, b, "save", at=NOW - timedelta(minutes=5))

    assert _metric(seeded_db, "north_star.meaningful_sessions").value == 1


def test_two_visits_far_apart_are_two_sessions(seeded_db: Session, user: User) -> None:
    """The spec counts sessions and never defines one; the gap is a documented choice, so
    it is worth pinning that it actually splits."""
    a, b = _papers(seeded_db, 2)
    morning = NOW - timedelta(hours=6)
    evening = morning + SESSION_GAP * 4

    _shown(seeded_db, user, a, at=morning, dwell=MEANINGFUL_DWELL_MS)
    _acted(seeded_db, user, a, "save", at=morning)
    _shown(seeded_db, user, b, at=evening, dwell=MEANINGFUL_DWELL_MS)
    _acted(seeded_db, user, b, "open_source", at=evening)

    assert _metric(seeded_db, "north_star.meaningful_sessions").value == 2


# ---------------------------------------------------------------------- guardrails


def test_showing_an_unlicensed_paper_is_counted(seeded_db: Session, user: User) -> None:
    """Zero by construction — ingestion refuses these (section 21). A non-zero value means
    that rule failed, not that a trend needs watching, so the check has to be able to fire."""
    assert _metric(seeded_db, "guard.unlicensed_shown").value == 0

    paper = _papers(seeded_db, 1)[0]
    paper.abstract_redistributable = False
    seeded_db.flush()
    _shown(seeded_db, user, paper, at=NOW - timedelta(minutes=5), dwell=1000)

    assert _metric(seeded_db, "guard.unlicensed_shown").value == 1


def test_the_ai_guardrail_counts_reports_against_cards_and_not_only_steps(
    seeded_db: Session, user: User
) -> None:
    """Found by running it: the guardrail read 0 against a database that had reports in it.

    A reader tapping 「説明が誤っている」 files against the *card*, and a card carries a
    `provenance_kind` of its own — counting only derivation steps missed most of them, which
    is the worst possible failure for a guardrail: quiet, and in the safe-looking direction.
    """
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()
    card = (
        seeded_db.execute(select(MathCard).where(MathCard.provenance_kind == "ai_explanation"))
        .scalars()
        .first()
    )
    if card is None:
        pytest.skip("no AI-authored card in the fixtures")

    before = _metric(seeded_db, "guard.ai_report_rate").value or 0.0

    seeded_db.add(
        ContentReport(
            user_id=user.id,
            entity_type="math_card",
            entity_id=card.id,
            math_card_id=card.id,
            reason="explanation_wrong",
            status="new",
        )
    )
    seeded_db.flush()

    after = _metric(seeded_db, "guard.ai_report_rate").value
    assert after is not None and after > before


def test_guardrails_are_marked_as_guardrails(seeded_db: Session, user: User) -> None:
    """A guardrail going up is a reason to stop, not a trend. The report has to say which
    is which, in the text as well as in the data."""
    report = collect(seeded_db, now=NOW)
    guards = [m for m in report.metrics if m.guardrail]

    assert {m.key for m in guards} >= {
        "guard.unlicensed_shown",
        "guard.near_full_translation_share",
        "guard.ingestion_runs",
        "guard.ai_report_rate",
        "guard.crash_and_gesture_failure",
    }
    assert all(line.startswith("!") for line in (m.render() for m in guards))
