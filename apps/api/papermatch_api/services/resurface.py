"""Bringing a saved paper back (spec section 9: 保存を墓場にしない再提示).

Section 9's worry is that saving becomes a way of not reading: the library fills up, nothing
comes back, and the act of saving quietly turns into filing. Its answer is to re-present
saved material — an expression, a maths step, the abstract's point — a few days later.

The Learn tab already does the expression half. This is the other one: a paper the reader
saved, never opened, and has not been reminded of.

**Not part of the 70/20/10 mix.** Section 16 fixes that ratio for *discovery*, and taking a
slot from it would mean the reader gets less of what they asked for while the counts still
claim 70/20/10. A returning paper is a different kind of card and it arrives as an extra one,
at most one per page.

**A return is labelled as a return.** The reader has seen this paper before, and presenting
it as a fresh discovery would make the feed look like it is repeating itself for no reason —
which is exactly how a reader learns to stop trusting the reasons.

**Never a paper they actually engaged with.** Opened, translated, marked as reading or
finished: that reader dealt with it, and bringing it back is nagging. Only 保存したまま触って
いない ones qualify.

**Nothing returns twice in a row.** A paper that came back and was still not opened has said
something; showing it again next session is the app insisting rather than reminding.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.models import Action, Paper, SavedPaper, User

__all__ = [
    "MIN_QUIET_DAYS",
    "REPEAT_COOLDOWN_DAYS",
    "Resurfaced",
    "candidates",
    "pick",
]

#: How long a saved paper must sit untouched before it is worth mentioning.
#:
#: Section 9 says 数日後. Shorter than this and the reminder arrives while the reader still
#: remembers saving it, which reads as the app not having noticed.
MIN_QUIET_DAYS = 3

#: How long after being re-presented a paper is left alone again.
#:
#: A paper that came back and was still not opened has told us something. Showing it again
#: the next day is the app insisting rather than reminding.
REPEAT_COOLDOWN_DAYS = 14

#: The one status that means untouched. Every other value in `savedStatus` — reading the
#: abstract, having finished it, having opened the source, Focus mode, finished, archived —
#: is the reader having engaged with the paper.
#:
#: Stated as "must be unread" rather than as a list of statuses to exclude. The first draft
#: excluded `{"reading", "finished", "archived"}`, and `reading` is not even a value in the
#: vocabulary — so `abstract_done` and `source_opened` papers would have been brought back to
#: readers who had plainly dealt with them. A whitelist cannot go out of date that way.
_UNTOUCHED_STATUS = "unread"

#: Action types that mean the same thing — the reader did something with this paper.
_ENGAGED_ACTIONS = frozenset({"open_source", "translate", "expand_math"})


@dataclass(frozen=True)
class Resurfaced:
    paper: Paper
    saved: SavedPaper
    #: Whole days since it was saved, so the card can say how long it has been waiting.
    quiet_days: int


def _days_between(earlier: datetime, later: datetime) -> int:
    return max(0, (later - earlier).days)


def candidates(session: Session, user: User, now: datetime | None = None) -> list[Resurfaced]:
    """Saved papers that qualify to come back, longest-waiting first.

    Everything is a real column: saved, never visited, still `unread`, no action recorded
    against it, and not already re-presented recently. A paper that fails any of these is
    not a weaker candidate — it is not a candidate, because each condition is a different
    way of the reader having already answered.
    """
    now = now or datetime.now(tz=UTC)
    quiet_before = now - timedelta(days=MIN_QUIET_DAYS)
    cooldown_before = now - timedelta(days=REPEAT_COOLDOWN_DAYS)

    engaged = set(
        session.execute(
            select(Action.paper_id).where(
                Action.user_id == user.id,
                Action.paper_id.is_not(None),
                Action.action_type.in_(_ENGAGED_ACTIONS),
            )
        ).scalars()
    )
    # Already brought back recently. Recorded as an action so it is in the audit trail like
    # everything else, rather than in a column only this feature reads.
    recently_resurfaced = set(
        session.execute(
            select(Action.paper_id).where(
                Action.user_id == user.id,
                Action.action_type == "resurface_saved",
                Action.created_at >= cooldown_before,
            )
        ).scalars()
    )

    rows = session.execute(
        select(SavedPaper, Paper)
        .join(Paper, Paper.id == SavedPaper.paper_id)
        .where(
            SavedPaper.user_id == user.id,
            SavedPaper.saved_at <= quiet_before,
            SavedPaper.last_visited_at.is_(None),
            SavedPaper.status == _UNTOUCHED_STATUS,
        )
        .order_by(SavedPaper.saved_at.asc())
    ).all()

    return [
        Resurfaced(paper=paper, saved=saved, quiet_days=_days_between(saved.saved_at, now))
        for saved, paper in rows
        if paper.id not in engaged and paper.id not in recently_resurfaced
    ]


def pick(session: Session, user: User, now: datetime | None = None) -> Resurfaced | None:
    """The one paper to bring back, or None.

    One, not a batch. Section 9 asks for 1件, and a page that returned five saved papers
    would stop being a discovery feed and start being a chore list.
    """
    found = candidates(session, user, now)
    return found[0] if found else None


def record(session: Session, user: User, paper_id: uuid.UUID) -> Action:
    """Note that this paper was brought back, so it is not brought back again next session."""
    row = Action(user_id=user.id, paper_id=paper_id, action_type="resurface_saved")
    session.add(row)
    session.flush()
    return row


def longest_waiting_days(session: Session, user: User, now: datetime | None = None) -> int:
    """How long the oldest untouched saved paper has been waiting, for section 27's metrics.

    Zero when there is none — which is the healthy state, not a missing measurement.
    """
    now = now or datetime.now(tz=UTC)
    oldest = session.execute(
        select(func.min(SavedPaper.saved_at)).where(
            SavedPaper.user_id == user.id,
            SavedPaper.last_visited_at.is_(None),
            SavedPaper.status == _UNTOUCHED_STATUS,
        )
    ).scalar_one_or_none()
    return 0 if oldest is None else _days_between(oldest, now)
