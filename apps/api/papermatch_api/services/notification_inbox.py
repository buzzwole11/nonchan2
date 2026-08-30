"""Generating the notifications a reader agreed to receive (spec sections 9, 10, 26).

`services/notifications.may_notify` is the rule; this is the writer that consults it. It
runs as a worker job, looks at what has actually happened — an expression fell due, a saved
paper grew a maths card, a saved paper was retracted or republished — and writes rows to the
inbox for the readers whose preset allows it.

**Everything is derived from state, so running twice is safe.** There is no queue of
pending events to lose or double-send: each candidate is "this entity, for this reader, in
this category", and the unique constraint on `(user, category, entity)` makes the second
attempt a no-op. A worker that crashed halfway resumes by simply running again.

**The preset gates generation, not display.** A `none` reader gets no rows at all — not
rows the client is trusted to hide. The decision's reason is frozen onto each row written,
so 「なぜ通知されたのか」 is answerable from the row alone (spec section 0: 監査ログ).

**Counting 「1日1回」 counts what was actually sent.** `already_sent_today` is read back
from the inbox itself in the reader's own timezone, so the daily budget survives worker
restarts and never resets at UTC midnight.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    Equation,
    ExpressionCard,
    MathCard,
    Notification,
    Paper,
    SavedPaper,
    User,
    UserSettings,
)
from papermatch_api.services.notifications import may_notify

__all__ = ["InboxReport", "generate_for_all", "generate_for_user"]


@dataclass
class InboxReport:
    """What one pass wrote, in the terms an operator asks about."""

    written: int = 0
    #: Refusals by `may_notify`, counted by reason — the normal case, not a failure.
    withheld: dict[str, int] = field(default_factory=dict)


def _local_day_bounds(now: datetime, timezone: str) -> tuple[datetime, datetime]:
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    local = now.astimezone(zone)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _sent_today(session: Session, user: User, now: datetime, timezone: str) -> int:
    start, end = _local_day_bounds(now, timezone)
    return int(
        session.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.created_at >= start,
                Notification.created_at < end,
            )
        ).scalar_one()
    )


@dataclass(frozen=True)
class _Candidate:
    category: str
    title: str
    body: str
    entity_type: str
    entity_id: str


def _already_notified(session: Session, user: User, candidate: _Candidate) -> bool:
    return (
        session.execute(
            select(Notification.id).where(
                Notification.user_id == user.id,
                Notification.category == candidate.category,
                Notification.entity_id == candidate.entity_id,
            )
        ).scalar_one_or_none()
        is not None
    )


def _review_due(session: Session, user: User, now: datetime) -> list[_Candidate]:
    """One notification per due *day*, not per due card.

    Ten expressions falling due together is one fact about the reader's day. Ten rows would
    spend the entire daily budget saying it, and teach the reader to ignore the category.
    The entity is the local date, which is also what makes the dedup key mean "already told
    them today".
    """
    due = session.execute(
        select(func.count())
        .select_from(ExpressionCard)
        .where(
            ExpressionCard.user_id == user.id,
            ExpressionCard.next_review_at.is_not(None),
            ExpressionCard.next_review_at <= now,
        )
    ).scalar_one()
    if not due:
        return []
    return [
        _Candidate(
            category="review_due",
            title="復習の時間です",
            body=f"見直しどきの表現が {due} 件あります",
            entity_type="expression",
            entity_id=f"due:{now.date().isoformat()}",
        )
    ]


def _saved_paper_updates(session: Session, user: User) -> list[_Candidate]:
    """Section 26's 重要時: a saved paper retracted or superseded.

    These are the two facts a reader must not keep reading in ignorance of, which is why
    `important_only` and `quiet` both let them through.
    """
    rows = session.execute(
        select(Paper)
        .join(SavedPaper, SavedPaper.paper_id == Paper.id)
        .where(SavedPaper.user_id == user.id)
    ).scalars()

    return [
        _Candidate(
            category="saved_paper_update",
            title="保存した論文に撤回情報",
            body=f"「{paper.title}」に撤回・懸念の情報が付きました（{paper.retraction_status}）",
            entity_type="paper",
            entity_id=str(paper.id),
        )
        for paper in rows
        if paper.retraction_status != "none"
    ]


def _new_math_cards(session: Session, user: User) -> list[_Candidate]:
    """Section 10's first entrance: 保存した論文に数式カードがある場合に通知."""
    saved_ids = set(
        session.execute(select(SavedPaper.paper_id).where(SavedPaper.user_id == user.id)).scalars()
    )
    if not saved_ids:
        return []

    found: list[_Candidate] = []
    for card in session.execute(select(MathCard)).scalars():
        equation_ids = [uuid.UUID(value) for value in card.source_equation_ids if value]
        if not equation_ids:
            continue
        paper_ids = set(
            session.execute(
                select(Equation.paper_id).where(Equation.id.in_(equation_ids))
            ).scalars()
        )
        for paper_id in paper_ids & saved_ids:
            paper = session.get(Paper, paper_id)
            if paper is None:
                continue
            found.append(
                _Candidate(
                    category="new_math_card",
                    title="保存した論文に数式カード",
                    body=f"「{paper.title}」の数式カード「{card.title}」が読めます",
                    entity_type="math_card",
                    entity_id=str(card.id),
                )
            )
            break
    return found


def generate_for_user(session: Session, user: User, now: datetime | None = None) -> InboxReport:
    """Write the notifications this reader's preset allows, and say why the rest were not."""
    report = InboxReport()
    now = now or datetime.now(tz=UTC)
    settings = session.get(UserSettings, user.id)
    if settings is None:
        return report
    preset = settings.notification_preset
    timezone = settings.timezone

    candidates = [
        *_saved_paper_updates(session, user),
        *_new_math_cards(session, user),
        *_review_due(session, user, now),
    ]

    for candidate in candidates:
        if _already_notified(session, user, candidate):
            continue
        sent_today = _sent_today(session, user, now, timezone)
        decision = may_notify(
            preset, candidate.category, now, timezone, already_sent_today=sent_today
        )
        if not decision.allowed:
            report.withheld[decision.reason] = report.withheld.get(decision.reason, 0) + 1
            continue
        session.add(
            Notification(
                user_id=user.id,
                category=candidate.category,
                title=candidate.title,
                body=candidate.body,
                entity_type=candidate.entity_type,
                entity_id=candidate.entity_id,
                decision_reason=decision.reason,
                # The generator's clock, not the database's. `_sent_today` reads this
                # column against the same clock, and the daily budget breaks the moment
                # the two disagree — which they did, under a test running at a fixed time.
                created_at=now,
            )
        )
        session.flush()
        report.written += 1
    return report


def generate_for_all(session: Session, now: datetime | None = None) -> InboxReport:
    """One pass over every reader. Idempotent, so a crashed worker simply runs again."""
    total = InboxReport()
    for user in session.execute(select(User)).scalars():
        report = generate_for_user(session, user, now)
        total.written += report.written
        for reason, count in report.withheld.items():
            total.withheld[reason] = total.withheld.get(reason, 0) + count
    return total
