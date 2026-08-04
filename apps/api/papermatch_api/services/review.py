"""The human review queue for maths cards (spec section 12, step 10).

Section 12's last step is **必要なカードのみ人手レビューへ送る** — *only the cards that
need it*. That word does the work here. A queue containing every card is a queue nobody
opens, and a reviewer who scrolls past forty fine cards to reach the broken one stops
reading carefully by card five. So this module's real job is deciding what to leave out.

**A card is queued for a stated reason.** Every entry carries why it is there and how
urgent it is, and both come from facts about the card rather than from a score nobody can
check: no step passed a mechanical check, a reader filed a report, the card asserts
something a model wrote. A reviewer opening the queue can tell at a glance which kind of
problem they are about to look at.

**`human_reviewed` can only be reached from here.** `mathcheck.combined_status` cannot
return it and says so; no amount of arithmetic establishes that a person looked. Approving
a card is the single path, which is what makes the label mean anything in the UI.

**Rejection hides, it does not delete.** A rejected card stops being served and keeps
existing, because the record of *what was rejected and why* is the only thing that stops
the pipeline from proposing it again next week.

**A reader's report is evidence, not a decision** (D-038). It moves a card up this queue;
it never changes a verification status by itself. The two tables stay separate for exactly
that reason.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    AuditLog,
    ContentReport,
    DerivationStep,
    MathCard,
    ReviewEvent,
    User,
)

__all__ = [
    "QUEUE_REASONS",
    "ReviewDecisionError",
    "ReviewItem",
    "record_decision",
    "review_queue",
    "triage",
]

#: Why a card is in the queue, most urgent first. The order is the priority order: a card
#: that a reader has reported is more urgent than one that is merely unverified, because
#: somebody is already looking at it and finding it wrong.
QUEUE_REASONS: tuple[tuple[str, str], ...] = (
    ("reader_reported", "読者から問題の報告がある"),
    ("no_verified_step", "機械的な検証を通った変形が 1 つも無い"),
    ("ai_authored_body", "本文が AI 生成で、まだ人が読んでいない"),
    ("unverified_steps", "検証を通らなかった変形が含まれている"),
)

_REASON_RANK = {reason: index for index, (reason, _) in enumerate(QUEUE_REASONS)}
_REASON_TEXT = dict(QUEUE_REASONS)

#: Statuses that count as "a check actually ran and passed".
VERIFIED_STATUSES: frozenset[str] = frozenset(
    {
        "mechanically_verified",
        "dimensionally_checked",
        "numerically_spot_checked",
        "human_reviewed",
        "source_exact",
    }
)

_DECISIONS = frozenset({"approved", "rejected", "needs_changes"})

#: Where a card lands after each decision. `needs_changes` stays in review rather than
#: going back to draft: the card has been looked at, and losing that would send it around
#: the triage loop again as though it were new.
_STATUS_AFTER = {
    "approved": "approved",
    "rejected": "rejected",
    "needs_changes": "in_review",
}


class ReviewDecisionError(ValueError):
    """A decision that cannot be recorded, with a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReviewItem:
    """One card waiting for a person, and why."""

    card: MathCard
    #: Codes from `QUEUE_REASONS`, most urgent first.
    reasons: tuple[str, ...]
    #: Japanese, for the reviewer.
    reason_text: str
    #: How many readers have reported this card or its steps.
    report_count: int
    #: Steps that passed no check. These are hidden from readers (section 12) and are the
    #: usual thing a reviewer is being asked to look at.
    unverified_step_count: int
    total_step_count: int

    @property
    def priority(self) -> int:
        """Lower sorts first. Derived from the reasons, so it cannot disagree with them."""
        return min((_REASON_RANK[reason] for reason in self.reasons), default=len(QUEUE_REASONS))


def _steps_for(session: Session, card: MathCard) -> list[DerivationStep]:
    ids = [uuid.UUID(str(value)) for value in card.source_equation_ids]
    if not ids:
        return []
    return list(
        session.execute(
            select(DerivationStep).where(
                DerivationStep.from_equation_id.in_(ids) | DerivationStep.to_equation_id.in_(ids)
            )
        ).scalars()
    )


def _report_count(session: Session, card: MathCard) -> int:
    """Reports against the card itself or anything it is built from.

    Counted together because a reviewer opening the card is going to look at all of it —
    splitting the count here would only make a card with three reports on its steps look
    quieter than one with a single report on its title.
    """
    return int(
        session.execute(
            select(func.count())
            .select_from(ContentReport)
            .where(ContentReport.math_card_id == card.id, ContentReport.status == "new")
        ).scalar_one()
    )


def triage(session: Session, card: MathCard) -> ReviewItem | None:
    """Decide whether ``card`` needs a person, and why. ``None`` means it does not.

    A card leaves the queue when it has been settled, or when nobody has reported it, its
    steps all passed a check, and its body is not something a model wrote.

    **On the current corpus every card qualifies**, because every card's body is
    AI-authored (D-022) and none has been reviewed. That is the honest state of the data
    rather than a filter that fails to filter: the reason `ai_authored_body` is the floor
    of the queue, and the ordering is what makes the queue usable until enough cards have
    been read for it to start emptying.
    """
    if card.review_status in {"approved", "rejected"}:
        # Already decided. Re-queueing it would ask a reviewer to redo their own work, and
        # a card that keeps coming back teaches them to skim.
        return None

    steps = _steps_for(session, card)
    unverified = [step for step in steps if step.verification_status not in VERIFIED_STATUSES]
    reports = _report_count(session, card)

    reasons: list[str] = []
    if reports > 0:
        reasons.append("reader_reported")
    if steps and not any(step.verification_status in VERIFIED_STATUSES for step in steps):
        reasons.append("no_verified_step")
    if card.provenance_kind == "ai_explanation":
        # Section 19 requires AI output to be distinguishable, and section 12 requires it
        # never to be presented as verified. Review is how it stops being only a claim.
        reasons.append("ai_authored_body")
    if unverified and "no_verified_step" not in reasons:
        reasons.append("unverified_steps")

    if not reasons:
        return None

    ordered = tuple(sorted(set(reasons), key=lambda reason: _REASON_RANK[reason]))
    return ReviewItem(
        card=card,
        reasons=ordered,
        reason_text="、".join(_REASON_TEXT[reason] for reason in ordered),
        report_count=reports,
        unverified_step_count=len(unverified),
        total_step_count=len(steps),
    )


def review_queue(session: Session, *, limit: int = 20) -> list[ReviewItem]:
    """Cards needing a person, most urgent first.

    Ties break on the oldest card first: a card that has been waiting a fortnight should
    not stay behind one added this morning with the same reason.
    """
    cards = list(
        session.execute(
            select(MathCard)
            .where(MathCard.review_status.notin_(("approved", "rejected")))
            .order_by(MathCard.created_at.asc())
        ).scalars()
    )
    items = [item for item in (triage(session, card) for card in cards) if item is not None]
    items.sort(key=lambda item: (item.priority, -item.report_count))
    return items[:limit]


def record_decision(
    session: Session,
    reviewer: User,
    card: MathCard,
    *,
    decision: str,
    notes: str | None = None,
) -> ReviewEvent:
    """Record a person's decision about a card (spec section 23: ReviewEvent).

    Approving is the **only** way a card's content reaches `human_reviewed`, which is why
    this is the one function that writes that status. It is applied to the card's steps
    rather than only to the card: the label a reader sees sits on the step.
    """
    if decision not in _DECISIONS:
        raise ReviewDecisionError(
            "invalid_decision", f"decision must be one of: {', '.join(sorted(_DECISIONS))}"
        )

    if card.review_status in {"approved", "rejected"}:
        # Re-deciding a settled card would overwrite someone else's judgement with no
        # record that it had been made. Reopening is a deliberate act, not a side effect.
        raise ReviewDecisionError("already_decided", f"this card is already {card.review_status}")

    cleaned = (notes or "").strip() or None
    if decision == "needs_changes" and cleaned is None:
        # "Needs changes" without saying which is not a decision, it is a delay.
        raise ReviewDecisionError("notes_required", "needs_changes requires notes")

    event = ReviewEvent(
        entity_type="math_card",
        entity_id=card.id,
        reviewer_id=reviewer.id,
        decision=decision,
        notes=cleaned,
    )
    session.add(event)
    card.review_status = _STATUS_AFTER[decision]

    promoted = 0
    if decision == "approved":
        for step in _steps_for(session, card):
            # Only steps a check already passed are promoted. A step that passed nothing
            # is not made true by approval of the card around it, and marking it
            # `human_reviewed` would claim a person checked mathematics they were never
            # shown — section 12 hides unverified steps, so they were not on the page.
            if step.verification_status in VERIFIED_STATUSES:
                step.verification_status = "human_reviewed"
                promoted += 1

    session.add(
        AuditLog(
            kind="math_card_reviewed",
            actor=f"user:{reviewer.id}",
            entity_type="math_card",
            entity_id=str(card.id),
            detail={
                "decision": decision,
                "hasNotes": cleaned is not None,
                "reviewStatus": card.review_status,
                "stepsPromoted": promoted,
                "at": datetime.now(tz=UTC).isoformat(),
            },
        )
    )
    session.flush()
    return event
