"""Section 27's numbers, computed from what the app actually records.

The point of this module is not the arithmetic — most of these are one query. It is that
**a metric nobody can compute is reported as absent rather than omitted**. A report showing
twelve numbers looks complete; a report showing twelve numbers and three explicit "no data
for this, and here is what is missing" lines tells you where you are actually blind. Two of
section 27's main metrics and one of its guardrails fall in the second group today, and
quietly dropping them would hide that.

Every rate names its denominator, because most of the mistakes available here are
denominator mistakes. "How often is a card read for ten seconds" over *all* impressions
counts cards whose dwell was never measured as cards nobody read; over impressions *with a
dwell recorded* it answers the question asked. The difference is not small — the first
number falls whenever the client fails to report, which is exactly when it should not move.

Guardrails are reported alongside the rest but they are not the same kind of number. A main
metric going up is good news. A guardrail going up is a reason to stop, and one of them —
権利不明コンテンツ表示件数 — should be zero by construction; a non-zero value means an
ingestion rule failed, not that a trend needs watching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    Action,
    ContentReport,
    DerivationStep,
    Impression,
    IngestionRun,
    MathCard,
    Paper,
    SavedPaper,
    TextSelection,
)
from papermatch_api.providers.local_embedding import cosine
from papermatch_api.services.embeddings import embeddings_for

__all__ = ["Metric", "MetricsReport", "collect"]

#: Section 27's own threshold: カード表示から10秒以上読まれた割合.
MEANINGFUL_DWELL_MS = 10_000

#: A gap longer than this starts a new session. The spec counts *sessions* in the North
#: Star but never defines one, and the app records no session id — so this is a choice, and
#: it is written here rather than buried in a query. Half an hour is long enough to survive
#: a phone call and short enough that morning and evening reading are not one session.
SESSION_GAP = timedelta(minutes=30)

#: Section 27 watches 保存後7日以内の再訪率 and, separately, the Saved 墓場率.
REVISIT_WINDOW = timedelta(days=7)
GRAVEYARD_AFTER = timedelta(days=30)

#: A selection covering this much of an abstract is closer to a full translation than to
#: the partial one section 7 is built around.
NEAR_FULL_SHARE = 0.8

#: Above this cosine two consecutive cards are "similar" for the purposes of section 27's
#: 連続類似カードに対するスキップ増加.
SIMILAR_ENOUGH = 0.35


@dataclass(frozen=True)
class Metric:
    key: str
    #: `None` means *not computable from what is recorded* — never "zero".
    value: float | int | None
    unit: str
    #: What it counts, or what is missing. Written for someone reading the output cold.
    detail: str
    #: Guardrails are read differently from the rest: up is bad, and one must stay at zero.
    guardrail: bool = False

    def render(self) -> str:
        mark = "!" if self.guardrail else " "
        if self.value is None:
            return f"{mark} {self.key:<34} —        {self.detail}"
        shown = f"{self.value:.3f}" if self.unit == "rate" else f"{self.value:g}"
        return f"{mark} {self.key:<34} {shown:<8} {self.detail}"


@dataclass
class MetricsReport:
    window_days: int
    generated_at: datetime
    metrics: list[Metric] = field(default_factory=list)

    @property
    def uncomputable(self) -> list[Metric]:
        return [m for m in self.metrics if m.value is None]

    def render(self) -> str:
        lines = [
            f"PaperMatch — section 27, last {self.window_days} days "
            f"(generated {self.generated_at.isoformat(timespec='seconds')})",
            "",
        ]
        lines += [m.render() for m in self.metrics]
        if self.uncomputable:
            lines += [
                "",
                f"{len(self.uncomputable)} of these cannot be computed from what is "
                "recorded today. They are listed rather than dropped so the gap is visible.",
            ]
        return "\n".join(lines)


def _rate(numerator: int, denominator: int) -> float | None:
    """`None` when there is nothing to divide by — not zero.

    A rate over an empty denominator is not 0%; it is unknown, and printing 0.000 for it
    would read as "nobody does this" when it means "nobody has had the chance yet".
    """
    return numerator / denominator if denominator else None


# ------------------------------------------------------------------------- North Star


def _sessions(stamps: list[datetime]) -> list[list[datetime]]:
    """Split one reader's card views into sessions on an inactivity gap."""
    grouped: list[list[datetime]] = []
    for stamp in sorted(stamps):
        if grouped and stamp - grouped[-1][-1] <= SESSION_GAP:
            grouped[-1].append(stamp)
        else:
            grouped.append([stamp])
    return grouped


def meaningful_sessions(session: Session, since: datetime) -> int:
    """Section 27's North Star candidate.

    「週内に、原文の一部を自力で読み、保存または原論文へ進んだ有意義なAbstractセッション数」

    Read as: a session containing at least one card the reader stayed on for the section 27
    threshold, *and* at least one save or jump to the source. 自力で is taken as "spent real
    time on the English", not "used no translation" — translating a selection is the product
    working rather than the reader failing, and section 9 already tracks the no-translation
    share as its own number.
    """
    rows = session.execute(
        select(Impression.user_id, Impression.shown_at, Impression.dwell_ms).where(
            Impression.shown_at >= since
        )
    ).all()

    read_by_user: dict[object, list[datetime]] = {}
    for user_id, shown_at, dwell in rows:
        if dwell is not None and dwell >= MEANINGFUL_DWELL_MS:
            read_by_user.setdefault(user_id, []).append(shown_at)

    acted = session.execute(
        select(Action.user_id, Action.created_at).where(
            Action.created_at >= since,
            Action.action_type.in_(("save", "open_source")),
            Action.undone.is_(False),
        )
    ).all()
    acted_by_user: dict[object, list[datetime]] = {}
    for user_id, created_at in acted:
        acted_by_user.setdefault(user_id, []).append(created_at)

    total = 0
    for user_id, stamps in read_by_user.items():
        actions = sorted(acted_by_user.get(user_id, []))
        for block in _sessions(stamps):
            start, end = block[0] - SESSION_GAP, block[-1] + SESSION_GAP
            if any(start <= when <= end for when in actions):
                total += 1
    return total


# ---------------------------------------------------------------------- main metrics


def _skip_lift_after_similar(session: Session, since: datetime) -> float | None:
    """Section 27: 連続類似カードに対するスキップ増加.

    How much more often a card is skipped when the card before it was about the same thing.
    Positive means the diversity control in section 16 is not working hard enough; the point
    of measuring it is that the feed already tries to prevent this, so a rise is evidence
    the prevention slipped rather than a fact about readers.
    """
    rows = session.execute(
        select(Impression.user_id, Impression.paper_id, Impression.shown_at)
        .where(Impression.shown_at >= since)
        .order_by(Impression.user_id, Impression.shown_at)
    ).all()
    if len(rows) < 2:
        return None

    skipped = {
        paper_id
        for (paper_id,) in session.execute(
            select(Action.paper_id).where(
                Action.created_at >= since,
                Action.action_type == "skip",
                Action.undone.is_(False),
            )
        ).all()
    }

    vectors = embeddings_for(session, [paper_id for _, paper_id, _ in rows])
    after_similar = [0, 0]
    after_different = [0, 0]

    for (prev_user, prev_paper, _), (user, paper, _) in pairwise(rows):
        if prev_user != user:
            continue
        a, b = vectors.get(prev_paper), vectors.get(paper)
        if a is None or b is None:
            continue
        bucket = after_similar if cosine(a, b) >= SIMILAR_ENOUGH else after_different
        bucket[1] += 1
        if paper in skipped:
            bucket[0] += 1

    similar = _rate(*after_similar)
    different = _rate(*after_different)
    if similar is None or different is None:
        return None
    return similar - different


# ------------------------------------------------------------------------ guardrails


def _unlicensed_impressions(session: Session, since: datetime) -> int:
    """Section 27: 権利不明コンテンツ表示件数. Zero by construction, checked anyway.

    Ingestion refuses to store a record whose terms do not permit keeping the abstract
    (section 21), so a non-zero answer here does not mean a trend to watch — it means that
    rule failed and something is on screen that should never have been stored.
    """
    return int(
        session.execute(
            select(func.count())
            .select_from(Impression)
            .join(Paper, Paper.id == Impression.paper_id)
            .where(Impression.shown_at >= since, Paper.abstract_redistributable.is_(False))
        ).scalar()
        or 0
    )


def _near_full_translation_share(session: Session, since: datetime) -> float | None:
    """Section 27: 全文に近い範囲の連続翻訳増加.

    Section 7 is built on translating a *selection*; a reader selecting almost the whole
    abstract every time is using it as a full-text translator, which is the thing the
    product deliberately does not offer.
    """
    rows = session.execute(
        select(TextSelection.start_offset, TextSelection.end_offset, func.length(Paper.abstract))
        .join(Paper, Paper.id == TextSelection.paper_id)
        .where(TextSelection.created_at >= since)
    ).all()
    if not rows:
        return None
    near_full = sum(
        1 for start, end, length in rows if length and (end - start) / length >= NEAR_FULL_SHARE
    )
    return near_full / len(rows)


def collect(
    session: Session, *, window_days: int = 7, now: datetime | None = None
) -> MetricsReport:
    now = now or datetime.now(tz=UTC)
    since = now - timedelta(days=window_days)
    report = MetricsReport(window_days=window_days, generated_at=now)
    add = report.metrics.append

    impressions = int(
        session.execute(
            select(func.count()).select_from(Impression).where(Impression.shown_at >= since)
        ).scalar()
        or 0
    )
    measured = int(
        session.execute(
            select(func.count())
            .select_from(Impression)
            .where(Impression.shown_at >= since, Impression.dwell_ms.is_not(None))
        ).scalar()
        or 0
    )
    read_through = int(
        session.execute(
            select(func.count())
            .select_from(Impression)
            .where(Impression.shown_at >= since, Impression.dwell_ms >= MEANINGFUL_DWELL_MS)
        ).scalar()
        or 0
    )

    def actions_of(kind: str) -> int:
        return int(
            session.execute(
                select(func.count())
                .select_from(Action)
                .where(
                    Action.created_at >= since,
                    Action.action_type == kind,
                    Action.undone.is_(False),
                )
            ).scalar()
            or 0
        )

    saves, opens, skips = actions_of("save"), actions_of("open_source"), actions_of("skip")
    undos = int(
        session.execute(
            select(func.count())
            .select_from(Action)
            .where(Action.created_at >= since, Action.action_type == "undo")
        ).scalar()
        or 0
    )

    # -------------------------------------------------------------------- North Star
    add(
        Metric(
            "north_star.meaningful_sessions",
            meaningful_sessions(session, since),
            "sessions",
            f"read >={MEANINGFUL_DWELL_MS // 1000}s and then saved or opened the source",
        )
    )

    # ------------------------------------------------------------------ main metrics
    add(
        Metric(
            "read.ten_second_share",
            _rate(read_through, measured),
            "rate",
            f"of the {measured} impressions with a dwell recorded",
        )
    )
    add(Metric("save.rate", _rate(saves, impressions), "rate", f"of {impressions} impressions"))
    add(Metric("source.open_rate", _rate(opens, impressions), "rate", "of impressions"))
    add(
        Metric(
            "undo.rate",
            _rate(undos, saves + skips),
            "rate",
            "of the actions that can be undone (save + skip)",
        )
    )

    selections = session.execute(
        select(TextSelection.start_offset, TextSelection.end_offset).where(
            TextSelection.created_at >= since
        )
    ).all()
    translated_papers = int(
        session.execute(
            select(func.count(func.distinct(TextSelection.paper_id))).where(
                TextSelection.created_at >= since
            )
        ).scalar()
        or 0
    )
    viewed_papers = int(
        session.execute(
            select(func.count(func.distinct(Impression.paper_id))).where(
                Impression.shown_at >= since
            )
        ).scalar()
        or 0
    )
    add(
        Metric(
            "translate.paper_share",
            _rate(translated_papers, viewed_papers),
            "rate",
            "of the distinct papers seen, at least one selection translated",
        )
    )
    add(
        Metric(
            "translate.mean_length",
            (sum(end - start for start, end in selections) / len(selections))
            if selections
            else None,
            "chars",
            f"mean selection length over {len(selections)} selections",
        )
    )

    saved_old_enough = int(
        session.execute(
            select(func.count())
            .select_from(SavedPaper)
            .where(SavedPaper.saved_at <= now - REVISIT_WINDOW)
        ).scalar()
        or 0
    )
    revisited = int(
        session.execute(
            select(func.count())
            .select_from(SavedPaper)
            .where(
                SavedPaper.saved_at <= now - REVISIT_WINDOW,
                SavedPaper.last_visited_at.is_not(None),
                SavedPaper.last_visited_at <= SavedPaper.saved_at + REVISIT_WINDOW,
            )
        ).scalar()
        or 0
    )
    add(
        Metric(
            "saved.revisit_within_7d",
            _rate(revisited, saved_old_enough),
            "rate",
            f"of the {saved_old_enough} saves old enough to judge",
        )
    )

    graveyard_pool = int(
        session.execute(
            select(func.count())
            .select_from(SavedPaper)
            .where(SavedPaper.saved_at <= now - GRAVEYARD_AFTER)
        ).scalar()
        or 0
    )
    graveyard = int(
        session.execute(
            select(func.count())
            .select_from(SavedPaper)
            .where(
                SavedPaper.saved_at <= now - GRAVEYARD_AFTER,
                SavedPaper.status == "unread",
                SavedPaper.last_visited_at.is_(None),
            )
        ).scalar()
        or 0
    )
    add(
        Metric(
            "saved.graveyard_share",
            _rate(graveyard, graveyard_pool),
            "rate",
            f"saved >{GRAVEYARD_AFTER.days}d ago, still unread and never opened",
        )
    )

    add(
        Metric(
            "skip.lift_after_similar_card",
            _skip_lift_after_similar(session, since),
            "rate",
            "skip rate after a similar card minus after a different one",
        )
    )

    # Two of section 27's main metrics have nothing behind them yet. Listed, not dropped.
    add(
        Metric(
            "math_card.completion_rate",
            None,
            "rate",
            "no completion event exists — nothing records finishing a maths card",
        )
    )
    add(
        Metric(
            "canvas.to_paper_rate",
            None,
            "rate",
            "Canvas is Phase 6; the screen it measures does not exist",
        )
    )

    # -------------------------------------------------------------------- guardrails
    add(
        Metric(
            "guard.unlicensed_shown",
            _unlicensed_impressions(session, since),
            "count",
            "must be 0 — ingestion refuses these (section 21)",
            guardrail=True,
        )
    )
    add(
        Metric(
            "guard.near_full_translation_share",
            _near_full_translation_share(session, since),
            "rate",
            f"selections covering >={NEAR_FULL_SHARE:.0%} of an abstract",
            guardrail=True,
        )
    )
    add(
        Metric(
            "guard.ingestion_runs",
            int(
                session.execute(
                    select(func.count())
                    .select_from(IngestionRun)
                    .where(IngestionRun.started_at >= since)
                ).scalar()
                or 0
            ),
            "count",
            "runs against sources in the window (section 27: 過剰APIアクセス)",
            guardrail=True,
        )
    )

    # Section 27's guardrail is AI説明の問題報告率 — reports about content a model wrote.
    # Counting only derivation steps missed most of them: a reader who taps
    # 「説明が誤っている」 on the card files against the *card*, and a card carries a
    # `provenance_kind` of its own. Running this and seeing 0 against a database that had
    # reports in it is what surfaced that.
    def reports_against(
        model: type[MathCard] | type[DerivationStep], entity: str
    ) -> dict[str, int]:
        rows = session.execute(
            select(model.provenance_kind, func.count(ContentReport.id))
            .join(
                ContentReport,
                and_(
                    ContentReport.entity_id == model.id,
                    ContentReport.entity_type == entity,
                ),
            )
            .where(ContentReport.created_at >= since)
            .group_by(model.provenance_kind)
        ).all()
        return {kind: int(count) for kind, count in rows}

    by_kind: dict[str, int] = {}
    for kind, count in (
        *reports_against(DerivationStep, "derivation_step").items(),
        *reports_against(MathCard, "math_card").items(),
    ):
        by_kind[kind] = by_kind.get(kind, 0) + count

    def ai_authored(model: type[MathCard] | type[DerivationStep]) -> int:
        return int(
            session.execute(
                select(func.count())
                .select_from(model)
                .where(model.provenance_kind == "ai_explanation")
            ).scalar()
            or 0
        )

    ai_items = ai_authored(DerivationStep) + ai_authored(MathCard)
    add(
        Metric(
            "guard.ai_report_rate",
            _rate(by_kind.get("ai_explanation", 0), ai_items),
            "rate",
            f"reports per AI-written card or step ({ai_items} exist); "
            f"all provenance: {by_kind or 'none reported'}",
            guardrail=True,
        )
    )
    add(
        Metric(
            "guard.crash_and_gesture_failure",
            None,
            "rate",
            "no client telemetry — nothing reports a crash or a failed gesture",
            guardrail=True,
        )
    )

    return report
