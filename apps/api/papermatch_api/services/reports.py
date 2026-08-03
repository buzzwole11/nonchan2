"""Reader reports on maths content (spec sections 12, 27).

Section 12 ends the pipeline with 必要なカードのみ人手レビューへ送る, and section 27 counts
AI説明の問題報告率 as a guardrail. Neither is possible without somewhere for a reader to say
"this looks wrong" — which, until this existed, the app had nowhere to put.

Three things a report deliberately does **not** do.

**It does not change `verification_status`.** That column is the record of which mechanical
checks ran and what they returned (`mathcheck/`). A reader's opinion is not a check. Letting
a report move it would put an unverified claim into the one field whose whole value is that
everything in it was verified — and the reader who then saw `numerically_spot_checked`
downgraded would have no way to tell whether a checker or a stranger had done it.

**It does not hide the card.** One reader reporting a formula is not grounds to remove
content from everyone; that is a decision, and `review_events` is where decisions go. What a
report does is make the card *findable* by whoever makes them.

**It does not promise a reply.** The response says what actually happened — the report was
recorded — and not that someone will look at it, because in this build nobody will yet.

One report per reader per problem per thing. A reader tapping twice is not two readers, and
section 27's metric is a rate; a second identical report updates the first instead of
counting again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api import vocab
from papermatch_api.models import AuditLog, ContentReport, DerivationStep, Equation, MathCard, User

__all__ = [
    "MAX_DETAIL_LENGTH",
    "ReportError",
    "report_counts_by_provenance",
    "submit_report",
]

#: The reader's own words are a pointer, not a discussion. Long enough for "the sign on the
#: second term is wrong", short enough that this never becomes a comment box.
MAX_DETAIL_LENGTH = 500


class ReportError(Exception):
    """Refused for a reason the caller should show, not a 500."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReportOutcome:
    report: ContentReport
    #: True when this replaced the reader's earlier report of the same problem.
    repeated: bool


def _resolve_target(
    session: Session, card: MathCard, step_id: uuid.UUID | None, equation_id: uuid.UUID | None
) -> tuple[str, uuid.UUID]:
    """Which thing the report is about, checked against the card it came from.

    The ids arrive from the client, so "a step" is not taken on trust: a request naming a
    step of some *other* card would otherwise let anyone attach a report to any row by
    guessing an id.
    """
    if step_id is not None and equation_id is not None:
        raise ReportError("ambiguous_target", "Report one step or one equation, not both")

    # A card owns equations, and a step belongs to a card by having both of its ends among
    # them (`services/equations.py`). There is no `math_card_id` on a step to trust, so the
    # containment is worked out the same way the card was assembled.
    owned = {str(eid) for eid in card.source_equation_ids}

    if step_id is not None:
        step = session.get(DerivationStep, step_id)
        if (
            step is None
            or str(step.from_equation_id) not in owned
            or str(step.to_equation_id) not in owned
        ):
            raise ReportError("unknown_step", "That step is not part of this card")
        return "derivation_step", step.id

    if equation_id is not None:
        if str(equation_id) not in owned:
            raise ReportError("unknown_equation", "That equation is not part of this card")
        equation = session.get(Equation, equation_id)
        if equation is None:
            raise ReportError("unknown_equation", "No such equation")
        return "equation", equation.id

    return "math_card", card.id


def submit_report(
    session: Session,
    user: User,
    card: MathCard,
    *,
    reason: str,
    step_id: uuid.UUID | None = None,
    equation_id: uuid.UUID | None = None,
    detail: str | None = None,
) -> ReportOutcome:
    """Record that a reader thinks something on this card is wrong."""
    if not vocab.is_valid("reportReason", reason):
        raise ReportError("invalid_reason", f"{reason!r} is not a report reason")

    cleaned = (detail or "").strip() or None
    if cleaned is not None and len(cleaned) > MAX_DETAIL_LENGTH:
        raise ReportError("detail_too_long", f"Keep the note under {MAX_DETAIL_LENGTH} characters")

    entity_type, entity_id = _resolve_target(session, card, step_id, equation_id)

    existing = session.execute(
        select(ContentReport).where(
            ContentReport.user_id == user.id,
            ContentReport.entity_type == entity_type,
            ContentReport.entity_id == entity_id,
            ContentReport.reason == reason,
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Not an error, and not a second row. The reader is allowed to add to what they
        # said; they are not allowed to count twice.
        #
        # A repeat with no note keeps the earlier note. Overwriting unconditionally threw
        # away what the reader had typed the moment they tapped the same chip again, which
        # is the opposite of "allowed to add".
        if cleaned is not None:
            existing.detail = cleaned
        existing.updated_at = datetime.now(tz=UTC)
        session.flush()
        return ReportOutcome(report=existing, repeated=True)

    row = ContentReport(
        user_id=user.id,
        entity_type=entity_type,
        entity_id=entity_id,
        math_card_id=card.id,
        reason=reason,
        detail=cleaned,
        status="new",
    )
    session.add(row)
    session.add(
        AuditLog(
            kind="content_reported",
            actor=f"user:{user.id}",
            entity_type=entity_type,
            entity_id=str(entity_id),
            detail={"reason": reason, "mathCardId": str(card.id), "hasNote": cleaned is not None},
        )
    )
    session.flush()
    return ReportOutcome(report=row, repeated=False)


def report_counts_by_provenance(session: Session) -> dict[str, int]:
    """Reports against derivation steps, split by where the step came from.

    This is section 27's guardrail (AI説明の問題報告率) in the only form that means
    anything: the number on its own says how much people complain, while the split says
    whether they complain more about what a model wrote than about what the paper said.
    """
    rows = session.execute(
        select(DerivationStep.provenance_kind, func.count(ContentReport.id))
        .join(ContentReport, ContentReport.entity_id == DerivationStep.id)
        .where(ContentReport.entity_type == "derivation_step")
        .group_by(DerivationStep.provenance_kind)
    ).all()
    return {kind: int(count) for kind, count in rows}
