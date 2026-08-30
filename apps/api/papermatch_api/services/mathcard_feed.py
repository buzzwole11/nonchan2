"""Offering a maths card in Discover, at low frequency (spec section 10).

Section 10 lists four entrances to a maths card, and this is the Discover one:
Discoverフィードへ低頻度で混ぜる. Two words of that carry the whole design.

**混ぜる — but not into the 70/20/10.** Same reasoning as the resurfaced paper (D-059):
section 16 fixes that ratio for paper discovery, and spending a slot on a maths card would
give the reader fewer papers while the counts still claimed 70/20/10. The card is an extra
entry on the page, clearly a different kind of thing, and the client renders it as an
invitation beside the deck rather than as a card inside it.

**低頻度 — which needs a memory.** Without one, "low frequency" is "on every first page".
The offer is recorded as a `mathcard_teaser` action (migration 0012), and nothing is
offered again for `COOLDOWN_DAYS`, whether or not it was opened. A reader who ignored the
invitation has answered it; repeating it next session is the app insisting.

**Only cards on papers the reader saved.** Section 10's other entrances (通知, Learn) are
also anchored to the reader's own library, and a maths card from a paper they never chose
is an advertisement, not a re-encounter. Within that, the paper they saved *longest ago*
comes first — the maths card is another way back into something at risk of being forgotten,
which is the same instinct as section 9.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import Action, Equation, MathCard, Paper, SavedPaper, User

__all__ = ["COOLDOWN_DAYS", "OfferedCard", "pick", "record"]

#: How long after one offer the feed stays quiet about maths cards. Section 10 says only
#: 低頻度; a week keeps the invitation rarer than the resurfaced paper (3 days quiet, D-059)
#: because a maths card asks for more of the reader than a saved abstract does.
COOLDOWN_DAYS = 7


@dataclass(frozen=True)
class OfferedCard:
    card: MathCard
    #: The saved paper the card belongs to — the reason this reader is seeing it.
    paper: Paper


def _paper_ids_of(session: Session, card: MathCard) -> set[uuid.UUID]:
    """The papers a card's equations come from. Almost always exactly one."""
    equation_ids = [uuid.UUID(value) for value in card.source_equation_ids]
    if not equation_ids:
        return set()
    return set(
        session.execute(select(Equation.paper_id).where(Equation.id.in_(equation_ids))).scalars()
    )


def pick(session: Session, user: User, now: datetime | None = None) -> OfferedCard | None:
    """The one card to offer, or None — and None is the common case by design."""
    now = now or datetime.now(tz=UTC)
    cooldown_before = now - timedelta(days=COOLDOWN_DAYS)

    recently_offered = session.execute(
        select(Action.id)
        .where(
            Action.user_id == user.id,
            Action.action_type == "mathcard_teaser",
            Action.created_at >= cooldown_before,
        )
        .limit(1)
    ).scalar_one_or_none()
    if recently_offered is not None:
        return None

    saved = list(
        session.execute(
            select(SavedPaper, Paper)
            .join(Paper, Paper.id == SavedPaper.paper_id)
            .where(SavedPaper.user_id == user.id)
            .order_by(SavedPaper.saved_at.asc())
        ).all()
    )
    if not saved:
        return None
    by_paper = {paper.id: paper for _, paper in saved}
    saved_order = {paper.id: index for index, (_, paper) in enumerate(saved)}

    cards = list(session.execute(select(MathCard)).scalars())
    candidates: list[tuple[int, MathCard, Paper]] = []
    for card in cards:
        for paper_id in _paper_ids_of(session, card):
            if paper_id in by_paper:
                candidates.append((saved_order[paper_id], card, by_paper[paper_id]))
                break

    if not candidates:
        return None
    # The card whose paper has been waiting longest — the same instinct as section 9's
    # resurfacing, reached through the maths instead of the abstract.
    candidates.sort(key=lambda entry: entry[0])
    _, card, paper = candidates[0]
    return OfferedCard(card=card, paper=paper)


def record(session: Session, user: User, offered: OfferedCard) -> Action:
    """Note the offer, so the next `COOLDOWN_DAYS` stay quiet."""
    row = Action(
        user_id=user.id,
        paper_id=offered.paper.id,
        action_type="mathcard_teaser",
        payload={"mathCardId": str(offered.card.id)},
    )
    session.add(row)
    session.flush()
    return row
