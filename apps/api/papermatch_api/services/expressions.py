"""Personal academic-English dictionary and its review schedule (spec section 9).

Spec section 9 sets the tone that shapes this module: 保存を墓場にしない — a saved
expression that is never seen again might as well not have been saved — and, from the same
section and section 10, 評価や罰ではなく / 派手な点数化はせず. So:

* The review answer is binary and unscored: ``again`` or ``got_it``. There is no grade, no
  streak, and nothing to lose.
* Intervals are a fixed, gentle ladder rather than an SM-2 style ease factor. A reader
  meeting one expression again a few days later is the whole ask; a system that punishes a
  missed day is not.
* An entry keeps the sentence it came from. Spec section 9 asks for 実際に読んだ論文の用例,
  and an entry without its context is a flashcard rather than a reading memory.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api import vocab
from papermatch_api.models import ExpressionCard, Paper, User
from papermatch_api.services.activity import ActivityError

#: Days until the next showing, indexed by how many times it has been reviewed.
#: Spec section 9 says 数日後に1件提示 — the first gap is days, not minutes.
REVIEW_LADDER_DAYS: tuple[int, ...] = (3, 7, 16, 35, 70)

#: Where a wrong answer sends an entry. Not back to zero: re-learning something you almost
#: had should not cost you everything, which is the "評価や罰ではなく" part.
AGAIN_STEP_BACK = 1


def next_interval_days(review_count: int) -> int:
    index = min(max(0, review_count), len(REVIEW_LADDER_DAYS) - 1)
    return REVIEW_LADDER_DAYS[index]


def _classify_kind(phrase: str) -> str:
    """Guess whether a phrase is a word, a collocation, a pattern or a sentence.

    Only a default: the client may state the kind, and this fills in when it does not.
    A "pattern" is something with a slot or a subordinator — the structural things spec
    section 9 lists under 構文.
    """
    stripped = phrase.strip()
    words = stripped.split()
    if len(words) == 1:
        return "word"
    if re.search(r"[.!?]$", stripped) and len(words) >= 5:
        return "sentence"
    if re.search(
        r"\b(that|which|whether|so that|such that|in order to|as (?:well|if))\b", stripped.lower()
    ):
        return "pattern"
    if len(words) <= 4:
        return "collocation"
    return "sentence" if len(words) > 8 else "pattern"


def save_expression(
    session: Session,
    user: User,
    *,
    phrase: str,
    meaning: str,
    kind: str | None = None,
    context: str | None = None,
    source_paper_id: uuid.UUID | None = None,
    example: str | None = None,
) -> tuple[ExpressionCard, bool]:
    """Add an entry, or enrich the one that already exists.

    Returns ``(card, created)``. Saving the same phrase twice merges rather than failing:
    meeting a phrase again in a second paper is a reason to keep both examples, not an
    error to show the reader.
    """
    cleaned = " ".join(phrase.split())
    if not cleaned:
        raise ActivityError("empty_phrase", "An expression needs a phrase")

    resolved_kind = kind or _classify_kind(cleaned)
    if not vocab.is_valid("expressionKind", resolved_kind):
        allowed = ", ".join(vocab.values("expressionKind"))
        raise ActivityError("invalid_expression_kind", f"kind must be one of: {allowed}")

    if source_paper_id is not None and session.get(Paper, source_paper_id) is None:
        raise ActivityError("paper_not_found", f"Unknown paper {source_paper_id}")

    existing = session.execute(
        select(ExpressionCard).where(
            ExpressionCard.user_id == user.id, ExpressionCard.phrase == cleaned
        )
    ).scalar_one_or_none()

    if existing is not None:
        if example and example not in existing.examples:
            existing.examples = [*existing.examples, example]
        if meaning and not existing.meaning:
            existing.meaning = meaning
        if context and not existing.context:
            existing.context = context
        session.flush()
        return existing, False

    now = datetime.now(tz=UTC)
    card = ExpressionCard(
        user_id=user.id,
        source_paper_id=source_paper_id,
        kind=resolved_kind,
        phrase=cleaned,
        meaning=meaning,
        context=context,
        examples=[example] if example else [],
        review_count=0,
        # Due after the first rung, not immediately: the reader has just seen it.
        next_review_at=now + timedelta(days=next_interval_days(0)),
    )
    session.add(card)
    session.flush()
    return card, True


def list_expressions(
    session: Session,
    user: User,
    *,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ExpressionCard], int]:
    base = select(ExpressionCard).where(ExpressionCard.user_id == user.id)
    if kind is not None:
        if not vocab.is_valid("expressionKind", kind):
            raise ActivityError("invalid_expression_kind", f"{kind!r} is not an expression kind")
        base = base.where(ExpressionCard.kind == kind)

    total = int(session.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    rows = list(
        session.execute(
            base.order_by(ExpressionCard.created_at.desc()).offset(offset).limit(limit)
        ).scalars()
    )
    return rows, total


def due_expressions(
    session: Session, user: User, *, limit: int = 5, now: datetime | None = None
) -> list[ExpressionCard]:
    """Entries ready to be seen again.

    Ordered by how overdue they are, so nothing is starved. ``limit`` defaults small on
    purpose: spec section 9 asks for 表現を1件提示, not a review queue to grind through.
    """
    now = now or datetime.now(tz=UTC)
    return list(
        session.execute(
            select(ExpressionCard)
            .where(
                ExpressionCard.user_id == user.id,
                ExpressionCard.next_review_at.is_not(None),
                ExpressionCard.next_review_at <= now,
            )
            .order_by(ExpressionCard.next_review_at.asc())
            .limit(limit)
        ).scalars()
    )


def record_review(
    session: Session,
    user: User,
    expression_id: uuid.UUID,
    outcome: str,
    *,
    now: datetime | None = None,
) -> ExpressionCard:
    """Record that an entry was reviewed and schedule the next showing."""
    if not vocab.is_valid("reviewOutcome", outcome):
        allowed = ", ".join(vocab.values("reviewOutcome"))
        raise ActivityError("invalid_review_outcome", f"outcome must be one of: {allowed}")

    card = session.execute(
        select(ExpressionCard).where(
            ExpressionCard.id == expression_id, ExpressionCard.user_id == user.id
        )
    ).scalar_one_or_none()
    if card is None:
        raise ActivityError("expression_not_found", "No such expression")

    now = now or datetime.now(tz=UTC)
    if outcome == "got_it":
        card.review_count += 1
    else:
        # Step back one rung rather than resetting. Losing every past review because of one
        # miss is the kind of punishment spec section 9 rules out.
        card.review_count = max(0, card.review_count - AGAIN_STEP_BACK)

    card.last_reviewed_at = now
    card.next_review_at = now + timedelta(days=next_interval_days(card.review_count))
    session.flush()
    return card


def delete_expression(session: Session, user: User, expression_id: uuid.UUID) -> bool:
    card = session.execute(
        select(ExpressionCard).where(
            ExpressionCard.id == expression_id, ExpressionCard.user_id == user.id
        )
    ).scalar_one_or_none()
    if card is None:
        return False
    session.delete(card)
    session.flush()
    return True


__all__ = [
    "REVIEW_LADDER_DAYS",
    "delete_expression",
    "due_expressions",
    "list_expressions",
    "next_interval_days",
    "record_review",
    "save_expression",
]
