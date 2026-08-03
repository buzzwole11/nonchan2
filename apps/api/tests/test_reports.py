"""Reader reports on maths content (spec sections 12, 27).

Almost every test here is about something a report must *not* do. Recording an opinion is
easy; what makes this feature safe is that an opinion cannot masquerade as a check, cannot
remove content, and cannot be counted twice.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.models import AuditLog, ContentReport, DerivationStep, MathCard, User
from papermatch_api.services.equations import derivation_steps_for
from papermatch_api.services.math_content import load_math_cards
from papermatch_api.services.reports import (
    MAX_DETAIL_LENGTH,
    ReportError,
    report_counts_by_provenance,
    submit_report,
)
from tests.conftest import FIXTURES_DIR, requires_db

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture
def math_db(seeded_db: Session) -> Session:
    """The sample corpus plus the hand-authored maths cards.

    Papers first: a card names its paper by canonical id, so loading the cards into an
    empty database would produce cards with nothing behind them.
    """
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()
    return seeded_db


@pytest.fixture
def user(math_db: Session) -> User:
    row = User(is_guest=True)
    math_db.add(row)
    math_db.flush()
    return row


@pytest.fixture
def card(math_db: Session) -> MathCard:
    row = math_db.execute(select(MathCard)).scalars().first()
    assert row is not None, "the maths fixtures should have loaded"
    return row


def _steps(session: Session, card: MathCard) -> list[DerivationStep]:
    ids = [uuid.UUID(str(i)) for i in card.source_equation_ids]
    return derivation_steps_for(session, ids, include_unverified=True)


# ------------------------------------------------------------------ what it records


def test_a_report_is_stored_against_the_card(math_db: Session, user: User, card: MathCard) -> None:
    outcome = submit_report(math_db, user, card, reason="explanation_wrong", detail="符号が逆です")

    assert outcome.repeated is False
    assert outcome.report.entity_type == "math_card"
    assert outcome.report.entity_id == card.id
    assert outcome.report.status == "new"
    assert outcome.report.detail == "符号が逆です"


def test_a_report_can_name_one_step(math_db: Session, user: User, card: MathCard) -> None:
    steps = _steps(math_db, card)
    if not steps:
        pytest.skip("this card has no derivation steps")

    outcome = submit_report(math_db, user, card, reason="step_wrong", step_id=steps[0].id)

    assert outcome.report.entity_type == "derivation_step"
    assert outcome.report.entity_id == steps[0].id
    # Kept so a step report can still be shown beside the card it came from.
    assert outcome.report.math_card_id == card.id


def test_every_report_leaves_an_audit_row(math_db: Session, user: User, card: MathCard) -> None:
    submit_report(math_db, user, card, reason="rendering_broken")
    rows = (
        math_db.execute(select(AuditLog).where(AuditLog.kind == "content_reported")).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].detail["reason"] == "rendering_broken"


# --------------------------------------------------------------- what it must not do


def test_a_report_does_not_change_verification_status(
    math_db: Session, user: User, card: MathCard
) -> None:
    """The single most important test in this file.

    `verification_status` records which mechanical checks ran and what they returned. A
    reader's opinion is not a check, and a reader who saw `numerically_spot_checked`
    downgraded would have no way to tell whether a checker or a stranger had done it.
    """
    steps = _steps(math_db, card)
    if not steps:
        pytest.skip("this card has no derivation steps")
    before = {s.id: s.verification_status for s in steps}

    submit_report(math_db, user, card, reason="step_wrong", step_id=steps[0].id)

    after = {s.id: s.verification_status for s in _steps(math_db, card)}
    assert after == before


def test_a_report_does_not_hide_the_card(math_db: Session, user: User, card: MathCard) -> None:
    """One reader is not grounds to remove content from everyone. That is a decision, and
    decisions live in `review_events`."""
    before = card.review_status
    submit_report(math_db, user, card, reason="formula_differs_from_paper")

    assert math_db.get(MathCard, card.id) is not None
    assert card.review_status == before


def test_reporting_twice_does_not_count_twice(math_db: Session, user: User, card: MathCard) -> None:
    """Section 27's metric is a *rate*; a reader tapping twice is not two readers."""
    submit_report(math_db, user, card, reason="other", detail="first")
    second = submit_report(math_db, user, card, reason="other", detail="second")

    assert second.repeated is True
    count = math_db.execute(select(func.count()).select_from(ContentReport)).scalar()
    assert count == 1
    assert second.report.detail == "second"


def test_a_repeat_without_a_note_keeps_the_note_already_there(
    math_db: Session, user: User, card: MathCard
) -> None:
    """Overwriting unconditionally threw away what the reader had typed the moment they
    tapped the same chip again — the opposite of "allowed to add to what they said"."""
    submit_report(math_db, user, card, reason="other", detail="λ の説明が違います")
    again = submit_report(math_db, user, card, reason="other")

    assert again.report.detail == "λ の説明が違います"


def test_two_readers_reporting_the_same_thing_are_two_reports(
    math_db: Session, user: User, card: MathCard
) -> None:
    other = User(is_guest=True)
    math_db.add(other)
    math_db.flush()

    submit_report(math_db, user, card, reason="other")
    submit_report(math_db, other, card, reason="other")

    assert math_db.execute(select(func.count()).select_from(ContentReport)).scalar() == 2


# ------------------------------------------------------------------- what it refuses


def test_a_step_from_another_card_is_refused(math_db: Session, user: User) -> None:
    """The ids come from the client. Without this, anyone could attach a report to any row
    by guessing an id."""
    cards = math_db.execute(select(MathCard)).scalars().all()
    assert len(cards) >= 2

    foreign = next(
        (s for c in cards[1:] for s in _steps(math_db, c) if s not in _steps(math_db, cards[0])),
        None,
    )
    if foreign is None:
        pytest.skip("no step outside the first card")

    with pytest.raises(ReportError) as caught:
        submit_report(math_db, user, cards[0], reason="step_wrong", step_id=foreign.id)
    assert caught.value.code == "unknown_step"


def test_a_reason_outside_the_vocabulary_is_refused(
    math_db: Session, user: User, card: MathCard
) -> None:
    with pytest.raises(ReportError) as caught:
        submit_report(math_db, user, card, reason="i_just_dont_like_it")
    assert caught.value.code == "invalid_reason"


def test_naming_both_a_step_and_an_equation_is_refused(
    math_db: Session, user: User, card: MathCard
) -> None:
    steps = _steps(math_db, card)
    if not steps:
        pytest.skip("this card has no derivation steps")
    with pytest.raises(ReportError) as caught:
        submit_report(
            math_db,
            user,
            card,
            reason="step_wrong",
            step_id=steps[0].id,
            equation_id=uuid.UUID(str(card.source_equation_ids[0])),
        )
    assert caught.value.code == "ambiguous_target"


def test_a_note_longer_than_the_limit_is_refused(
    math_db: Session, user: User, card: MathCard
) -> None:
    """A report is a pointer, not a discussion."""
    with pytest.raises(ReportError) as caught:
        submit_report(math_db, user, card, reason="other", detail="x" * (MAX_DETAIL_LENGTH + 1))
    assert caught.value.code == "detail_too_long"


def test_an_empty_note_is_stored_as_no_note(math_db: Session, user: User, card: MathCard) -> None:
    outcome = submit_report(math_db, user, card, reason="other", detail="   ")
    assert outcome.report.detail is None


# ------------------------------------------------------------------ the guardrail


def test_reports_are_countable_by_where_the_content_came_from(
    math_db: Session, user: User, card: MathCard
) -> None:
    """Spec section 27's guardrail is AI説明の問題報告率, which needs the split rather than
    the total: the number alone says how much people complain, the split says whether they
    complain more about what a model wrote than about what the paper said."""
    steps = _steps(math_db, card)
    if not steps:
        pytest.skip("this card has no derivation steps")

    submit_report(math_db, user, card, reason="step_wrong", step_id=steps[0].id)

    counts = report_counts_by_provenance(math_db)
    assert counts.get(steps[0].provenance_kind) == 1
