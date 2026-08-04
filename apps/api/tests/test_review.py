"""The human review queue (spec section 12, step 10).

Two things are load-bearing and both are about what review *means*:

* `human_reviewed` is reachable only by a person approving a card. If arithmetic could
  produce it, the label would say nothing the other statuses do not already say.
* Approval does not launder an unverified step. A reviewer is shown what the reader is
  shown, and section 12 hides unverified steps — so they were not on the page.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import AuditLog, ContentReport, DerivationStep, MathCard, User
from papermatch_api.services.math_content import load_math_cards
from papermatch_api.services.review import (
    QUEUE_REASONS,
    ReviewDecisionError,
    record_decision,
    review_queue,
    triage,
)
from tests.conftest import FIXTURES_DIR, requires_db

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture
def math_db(seeded_db: Session) -> Session:
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()
    return seeded_db


@pytest.fixture
def reviewer(math_db: Session) -> User:
    row = User(is_guest=False)
    math_db.add(row)
    math_db.flush()
    return row


@pytest.fixture
def card(math_db: Session) -> MathCard:
    row = math_db.execute(select(MathCard)).scalars().first()
    assert row is not None
    return row


def _steps(session: Session, card: MathCard) -> list[DerivationStep]:
    ids = [uuid.UUID(str(value)) for value in card.source_equation_ids]
    return list(
        session.execute(
            select(DerivationStep).where(DerivationStep.from_equation_id.in_(ids))
        ).scalars()
    )


# ------------------------------------------------------------------ triage


def test_an_ai_authored_card_needs_a_person(math_db: Session, card: MathCard) -> None:
    # Section 19 requires AI output to be distinguishable and section 12 forbids
    # presenting it as verified; review is how it stops being only a claim.
    item = triage(math_db, card)

    assert item is not None
    assert "ai_authored_body" in item.reasons


def test_a_card_with_no_verified_step_is_named_as_such(math_db: Session) -> None:
    """The fixture carries one card built specifically to have nothing verified."""
    items = review_queue(math_db, limit=20)

    assert any("no_verified_step" in item.reasons for item in items)


def test_a_settled_card_leaves_the_queue(math_db: Session, card: MathCard) -> None:
    # Re-queueing a decided card asks a reviewer to redo their own work, and a card that
    # keeps coming back teaches them to skim.
    card.review_status = "approved"
    math_db.flush()

    assert triage(math_db, card) is None


def test_a_rejected_card_also_leaves_the_queue(math_db: Session, card: MathCard) -> None:
    card.review_status = "rejected"
    math_db.flush()

    assert triage(math_db, card) is None


def test_a_clean_non_ai_card_needs_nobody(math_db: Session, card: MathCard) -> None:
    card.provenance_kind = "original"
    for step in _steps(math_db, card):
        step.verification_status = "mechanically_verified"
    for report in math_db.execute(
        select(ContentReport).where(ContentReport.math_card_id == card.id)
    ).scalars():
        report.status = "resolved"
    math_db.flush()

    assert triage(math_db, card) is None


# ------------------------------------------------------------------ ordering


def test_a_reported_card_sorts_above_an_unreported_one(
    math_db: Session, card: MathCard, reviewer: User
) -> None:
    """A reader has already looked and found it wrong; that outranks a guess."""
    math_db.add(
        ContentReport(
            user_id=reviewer.id,
            entity_type="math_card",
            entity_id=card.id,
            math_card_id=card.id,
            reason="explanation_wrong",
            status="new",
        )
    )
    math_db.flush()

    items = review_queue(math_db, limit=20)

    assert items[0].card.id == card.id
    assert "reader_reported" in items[0].reasons


def test_priority_is_derived_from_the_reasons(math_db: Session) -> None:
    # Not a separate number: a score that could disagree with the stated reason would make
    # the queue's explanation untrustworthy.
    for item in review_queue(math_db, limit=20):
        expected = min(
            index for index, (reason, _) in enumerate(QUEUE_REASONS) if reason in item.reasons
        )
        assert item.priority == expected


def test_the_queue_respects_its_limit(math_db: Session) -> None:
    assert len(review_queue(math_db, limit=2)) <= 2


# ------------------------------------------------------------------ decisions


def test_approval_is_the_only_route_to_human_reviewed(
    math_db: Session, reviewer: User, card: MathCard
) -> None:
    for step in _steps(math_db, card):
        step.verification_status = "mechanically_verified"
    math_db.flush()

    record_decision(math_db, reviewer, card, decision="approved")

    assert all(step.verification_status == "human_reviewed" for step in _steps(math_db, card))
    assert card.review_status == "approved"


def test_approval_does_not_launder_an_unverified_step(
    math_db: Session, reviewer: User, card: MathCard
) -> None:
    """Section 12 hides unverified steps, so the reviewer was never shown this one.

    Marking it `human_reviewed` would claim a person checked mathematics that was not on
    the page — the worst possible thing for a label whose entire value is that it is true.
    """
    steps = _steps(math_db, card)
    assert steps, "this card should have steps"
    steps[0].verification_status = "unverified"
    math_db.flush()

    record_decision(math_db, reviewer, card, decision="approved")

    assert _steps(math_db, card)[0].verification_status == "unverified"


def test_a_rejected_card_is_hidden_rather_than_deleted(
    math_db: Session, reviewer: User, card: MathCard
) -> None:
    # The record of what was rejected and why is the only thing stopping the pipeline from
    # proposing it again next week.
    record_decision(math_db, reviewer, card, decision="rejected", notes="導出が誤り")

    assert card.review_status == "rejected"
    assert math_db.execute(select(MathCard).where(MathCard.id == card.id)).scalar_one() is card


def test_needs_changes_keeps_the_card_in_review(
    math_db: Session, reviewer: User, card: MathCard
) -> None:
    # Not back to draft: the card has been looked at, and losing that would send it round
    # the triage loop as though it were new.
    record_decision(math_db, reviewer, card, decision="needs_changes", notes="記号の説明が不足")

    assert card.review_status == "in_review"


def test_needs_changes_without_notes_is_refused(
    math_db: Session, reviewer: User, card: MathCard
) -> None:
    """Saying "needs changes" without saying which is a delay, not a decision."""
    with pytest.raises(ReviewDecisionError) as raised:
        record_decision(math_db, reviewer, card, decision="needs_changes")

    assert raised.value.code == "notes_required"


def test_a_settled_card_cannot_be_decided_again(
    math_db: Session, reviewer: User, card: MathCard
) -> None:
    # Overwriting someone else's judgement with no record that it was made.
    record_decision(math_db, reviewer, card, decision="approved")

    with pytest.raises(ReviewDecisionError) as raised:
        record_decision(math_db, reviewer, card, decision="rejected", notes="やはり違う")

    assert raised.value.code == "already_decided"


def test_an_unknown_decision_is_refused(math_db: Session, reviewer: User, card: MathCard) -> None:
    with pytest.raises(ReviewDecisionError) as raised:
        record_decision(math_db, reviewer, card, decision="looks_fine")

    assert raised.value.code == "invalid_decision"


def test_every_decision_is_written_to_the_audit_log(
    math_db: Session, reviewer: User, card: MathCard
) -> None:
    record_decision(math_db, reviewer, card, decision="rejected", notes="誤り")

    entry = math_db.execute(
        select(AuditLog).where(
            AuditLog.kind == "math_card_reviewed", AuditLog.entity_id == str(card.id)
        )
    ).scalar_one()
    assert entry.detail["decision"] == "rejected"
    assert entry.actor == f"user:{reviewer.id}"


def test_a_decided_card_does_not_come_back_to_the_queue(
    math_db: Session, reviewer: User, card: MathCard
) -> None:
    record_decision(math_db, reviewer, card, decision="approved")

    assert all(item.card.id != card.id for item in review_queue(math_db, limit=50))
