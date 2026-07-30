"""Discover feed construction (spec sections 6, 16).

The feed is built from what is already in the database, never by calling a provider
during the request. Ingestion runs separately, so an unreachable provider degrades the
*freshness* of the feed rather than its availability (spec section 25:
外部API失敗時もキャッシュ済みフィードを表示).

Three rules from the spec drive the design, and each is implemented as its own visible
step rather than folded into one score:

* **70 / 20 / 10.** Section 16 fixes the mix at 70% chosen fields, 20% adjacent fields,
  10% unexplored. That is a *slot allocation*, not a set of score weights, so candidates
  are partitioned into three pools and slots are handed out. This is also what makes the
  reason label on each card truthful: a card in the adjacent pool is there *because* it
  is adjacent.
* **Reasons are explainable.** Section 6: 単一の不透明なスコアだけを見せない. Every item
  carries the labels that put it where it is.
* **Nothing is shown twice.** Section 16: 一度表示した論文は原則再表示しない, with narrow
  re-injection conditions implemented in :func:`reinjectable_paper_ids`.

Phase 3 replaces the within-pool scoring with embedding similarity. The pool split, the
diversity pass and the reason labels stay.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from papermatch_api.models import (
    Action,
    Field,
    Impression,
    Interest,
    Paper,
    SavedPaper,
    User,
)
from papermatch_api.text.normalize import normalize_author_key

#: Section 16 mix. Kept as data so the split is inspectable and testable.
POOL_ALLOCATION: dict[str, float] = {
    "matched": 0.70,
    "adjacent": 0.20,
    "exploration": 0.10,
}

#: Dwell above this counts as real reading, which blocks re-injection (section 16).
MEANINGFUL_DWELL_MS = 10_000

#: How far back the diversity pass looks when suppressing repeats (section 16).
DIVERSITY_WINDOW = 20

#: Actions that mean "do not show me this kind of thing for a while" (section 16).
SUPPRESSION_ACTIONS = ("hide_topic", "hide_author")
SUPPRESSION_DAYS = 30

#: Minimum field weight for a paper to count as belonging to that field when choosing a
#: pool. Below this the tag is incidental, not what the paper is about.
SIGNIFICANT_FIELD_WEIGHT = 0.15

#: Ceiling on how deep each pool is ranked. The whole sequence is built per request so
#: that paging stays stable, and this keeps that cost bounded as the corpus grows.
MAX_CANDIDATES_PER_POOL = 500


@dataclass
class Candidate:
    paper: Paper
    pool: str
    score: float
    reasons: list[str] = dataclass_field(default_factory=list)
    #: Components kept for the API response and for debugging a surprising ranking.
    breakdown: dict[str, float] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class FeedCursor:
    """Opaque paging token.

    ``seed`` freezes the exploration-pool shuffle so successive pages of one snapshot
    stay consistent; ``offset`` walks that snapshot. A request with no cursor starts a new
    snapshot, which is what re-applies the impression exclusions the client has recorded
    in the meantime.
    """

    seed: int
    offset: int

    def encode(self) -> str:
        return f"{self.seed}:{self.offset}"

    @classmethod
    def decode(cls, raw: str | None) -> FeedCursor | None:
        if not raw:
            return None
        seed_part, _, offset_part = raw.partition(":")
        try:
            return cls(seed=int(seed_part), offset=int(offset_part))
        except ValueError:
            return None


@dataclass
class FeedPage:
    items: list[Candidate]
    next_cursor: str | None
    #: True when the newest metadata could not be fetched, so this page is cache-only.
    degraded: bool
    #: How many candidates existed before paging — used by tests and diagnostics.
    candidate_count: int


# --------------------------------------------------------------------------- exclusions


def _suppression_cutoff(now: datetime) -> datetime:
    return now - timedelta(days=SUPPRESSION_DAYS)


def suppressed_field_ids(session: Session, user: User, now: datetime | None = None) -> set[str]:
    """Fields the user asked to see less of, within the suppression window.

    Derived from the action log rather than a separate preferences table, so that undoing
    a ``hide_topic`` action undoes the suppression too — no extra bookkeeping, and the
    audit trail is the same one the Undo button already uses.
    """
    now = now or datetime.now(tz=UTC)
    rows = session.execute(
        select(Action).where(
            Action.user_id == user.id,
            Action.action_type == "hide_topic",
            Action.undone.is_(False),
            Action.created_at >= _suppression_cutoff(now),
        )
    ).scalars()
    suppressed: set[str] = set()
    for row in rows:
        value = row.payload.get("fieldId")
        if isinstance(value, str):
            suppressed.add(value)
    return suppressed


def suppressed_author_keys(session: Session, user: User, now: datetime | None = None) -> set[str]:
    now = now or datetime.now(tz=UTC)
    rows = session.execute(
        select(Action).where(
            Action.user_id == user.id,
            Action.action_type == "hide_author",
            Action.undone.is_(False),
            Action.created_at >= _suppression_cutoff(now),
        )
    ).scalars()
    keys: set[str] = set()
    for row in rows:
        value = row.payload.get("authorName")
        if isinstance(value, str) and value.strip():
            keys.add(normalize_author_key(value))
    return keys


def reinjectable_paper_ids(
    session: Session, user: User, now: datetime | None = None
) -> set[uuid.UUID]:
    """Papers that were shown before but may return (spec section 16).

    All three conditions must hold: the reshow window has elapsed, the only thing the user
    ever did was skip, and they never dwelled long enough for it to count as read. A paper
    that was saved, translated, or opened is never re-injected — the user already dealt
    with it.
    """
    now = now or datetime.now(tz=UTC)
    window_days = user.settings.reshow_after_days
    if window_days <= 0:
        return set()
    cutoff = now - timedelta(days=window_days)

    last_seen = (
        select(
            Impression.paper_id.label("paper_id"),
            func.max(Impression.shown_at).label("last_shown"),
            func.max(func.coalesce(Impression.dwell_ms, 0)).label("max_dwell"),
        )
        .where(Impression.user_id == user.id)
        .group_by(Impression.paper_id)
        .subquery()
    )

    engaged = (
        select(Action.paper_id)
        .where(
            Action.user_id == user.id,
            Action.undone.is_(False),
            Action.action_type.notin_(("skip", "undo")),
            Action.paper_id.is_not(None),
        )
        .subquery()
    )

    rows = session.execute(
        select(last_seen.c.paper_id).where(
            last_seen.c.last_shown < cutoff,
            last_seen.c.max_dwell < MEANINGFUL_DWELL_MS,
            last_seen.c.paper_id.notin_(select(engaged.c.paper_id)),
        )
    ).scalars()
    return set(rows)


# --------------------------------------------------------------------------- candidates


def _candidate_query(user: User, reinjectable: set[uuid.UUID]) -> Select[tuple[Paper]]:
    seen = select(Impression.paper_id).where(Impression.user_id == user.id)
    saved = select(SavedPaper.paper_id).where(SavedPaper.user_id == user.id)

    stmt = (
        select(Paper)
        .options(selectinload(Paper.identifiers), selectinload(Paper.field_weights))
        .where(
            # Withdrawn work never enters a feed (spec section 21).
            Paper.retraction_status.notin_(("withdrawn", "retracted")),
            # Already saved means already dealt with; it belongs in Saved, not Discover.
            Paper.id.notin_(saved),
        )
    )
    if reinjectable:
        stmt = stmt.where(or_(Paper.id.notin_(seen), Paper.id.in_(list(reinjectable))))
    else:
        stmt = stmt.where(Paper.id.notin_(seen))
    return stmt


# ------------------------------------------------------------------------------ scoring


def _freshness(year: int, now_year: int) -> float:
    """1.0 for this year, decaying to 0 over roughly a decade."""
    age = max(0, now_year - year)
    return max(0.0, 1.0 - age / 10.0)


def _difficulty_fit(paper: Paper, user: User) -> float:
    """How well the paper's English and maths load match the user's declared levels.

    Spec section 18 lets the user say where they are; a paper far above or below that is
    less useful even if the topic is a perfect match.
    """
    english_order = ["beginner", "intermediate", "advanced", "native_like"]
    try:
        want = english_order.index(user.settings.english_level)
        have = english_order.index(paper.english_level)
    except ValueError:
        want = have = 1
    english_fit = 1.0 - abs(want - have) / (len(english_order) - 1)

    # Maths level 0 means "do not show me formulas at all" (spec section 18).
    math_level = user.settings.math_level
    if math_level == "level_0":
        math_fit = 1.0 if paper.math_density <= 0.5 else 0.0
    else:
        wanted_density = {"level_1": 1.0, "level_2": 2.5, "level_3": 4.0, "level_4": 6.0}.get(
            math_level, 2.5
        )
        math_fit = max(0.0, 1.0 - abs(paper.math_density - wanted_density) / 8.0)

    return 0.5 * english_fit + 0.5 * math_fit


def _quality_proxy(paper: Paper) -> float:
    """A deliberately weak stand-in, not a judgement of the work.

    Spec section 2 is explicit that this is not a peer-review-quality app, so nothing here
    claims to measure merit. It only prefers records we can actually show well: open
    access, a real venue, a resolvable identifier.
    """
    score = 0.0
    if paper.open_access in {"gold", "green", "hybrid"}:
        score += 0.5
    if paper.venue:
        score += 0.25
    if any(i.kind in {"doi", "arxiv"} for i in paper.identifiers):
        score += 0.25
    return min(1.0, score)


def _interest_strength(paper: Paper, interests: dict[str, Interest]) -> float:
    weights = {fw.field_id: fw.weight for fw in paper.field_weights}
    if paper.primary_field_id:
        weights.setdefault(paper.primary_field_id, 0.5)
    best = 0.0
    for field_id, weight in weights.items():
        interest = interests.get(field_id)
        if interest is None:
            continue
        best = max(best, interest.strength * max(0.2, weight))
    return best


def significant_fields(paper: Paper) -> set[str]:
    """Fields the paper is actually about.

    A paper usually carries a long tail of low-weight field tags. Treating any of them as
    "this is one of your chosen fields" would put almost everything in the matched pool
    and quietly destroy the 70/20/10 mix — a machine-learning paper with a 0.1 tag for
    high-energy theory is not a high-energy theory paper. The threshold keeps the primary
    field and its parent, and drops the incidental tags.
    """
    fields = {fw.field_id for fw in paper.field_weights if fw.weight >= SIGNIFICANT_FIELD_WEIGHT}
    if paper.primary_field_id:
        fields.add(paper.primary_field_id)
    return fields


def _pool_for(
    paper: Paper,
    interest_field_ids: set[str],
    adjacent_field_ids: set[str],
) -> str:
    paper_fields = significant_fields(paper)
    if paper_fields & interest_field_ids:
        return "matched"
    if paper_fields & adjacent_field_ids:
        return "adjacent"
    return "exploration"


def _first_author_key(paper: Paper) -> str | None:
    authors = paper.authors or []
    if not authors:
        return None
    head = authors[0]
    name = head.get("name") if isinstance(head, dict) else None
    return normalize_author_key(name) if isinstance(name, str) else None


# ---------------------------------------------------------------------------- diversity


class _DiversityState:
    """Tracks what was shown recently so the next pick can avoid repeating it."""

    def __init__(self, recent_fields: list[str]) -> None:
        self._fields = list(recent_fields[-DIVERSITY_WINDOW:])
        self._authors: list[str] = []

    def repeats(self, candidate: Candidate) -> bool:
        field_id = candidate.paper.primary_field_id
        author = _first_author_key(candidate.paper)
        repeats_field = bool(field_id) and self._fields[-1:] == [field_id]
        repeats_author = bool(author) and author in self._authors[-3:]
        return repeats_field or repeats_author

    def record(self, candidate: Candidate) -> None:
        if candidate.paper.primary_field_id:
            self._fields.append(candidate.paper.primary_field_id)
        author = _first_author_key(candidate.paper)
        if author:
            self._authors.append(author)


# --------------------------------------------------------------------------------- feed


def mix_pattern() -> list[tuple[str, int]]:
    """The 70/20/10 mix expressed as one block of ten slots.

    Derived from :data:`POOL_ALLOCATION` so the mix has exactly one definition.
    """
    return [(name, round(share * 10)) for name, share in POOL_ALLOCATION.items()]


def _sequence(pools: dict[str, list[Candidate]], recent_fields: list[str]) -> list[Candidate]:
    """Order every candidate: the 70/20/10 mix and the diversity rule, in one pass.

    Doing these together matters. Run separately, the diversity pass reorders the mixed
    sequence and quietly erodes the ratio — deferring an adjacent card pulls a chosen-field
    card forward, and a page that should have been 7/2/1 comes out 9/1/0. Here each slot
    first decides *which pool* it belongs to (the mix) and only then *which candidate* from
    that pool reads best after the previous card (the diversity rule), so neither
    requirement can eat the other.

    Both decisions look only at what came before, so the sequence has a stable prefix:
    extending it can never reorder a card the client has already been shown, which is what
    makes cursor paging safe.
    """
    pattern = mix_pattern()
    remaining = {name: list(items) for name, items in pools.items()}
    total = sum(len(items) for items in remaining.values())
    state = _DiversityState(recent_fields)
    ordered: list[Candidate] = []

    def take(pool_name: str) -> Candidate | None:
        items = remaining[pool_name]
        if not items:
            return None
        index = next(
            (i for i, candidate in enumerate(items) if not state.repeats(candidate)),
            # Everything left in this pool repeats something; take the best rather than
            # leave the slot empty. The user did ask for this topic.
            0,
        )
        candidate = items.pop(index)
        state.record(candidate)
        return candidate

    while len(ordered) < total:
        progressed = False
        for pool_name, count in pattern:
            for _ in range(count):
                candidate = take(pool_name)
                if candidate is None:
                    break
                ordered.append(candidate)
                progressed = True
        if not progressed:
            break
    return ordered


def build_feed(
    session: Session,
    user: User,
    *,
    limit: int = 20,
    cursor: str | None = None,
    degraded: bool = False,
    now: datetime | None = None,
) -> FeedPage:
    now = now or datetime.now(tz=UTC)
    parsed = FeedCursor.decode(cursor)
    seed = parsed.seed if parsed else random.randrange(1, 2**31)
    offset = parsed.offset if parsed else 0

    interests = {
        interest.field_id: interest
        for interest in session.execute(
            select(Interest).where(Interest.user_id == user.id)
        ).scalars()
    }
    interest_field_ids = set(interests)

    # "Adjacent" means a sibling under the same parent field, plus the parent itself
    # (spec section 6: 隣接分野探索).
    parents = {row.id: row.parent_id for row in session.execute(select(Field)).scalars()}
    interest_parents: set[str] = {
        parent for f in interest_field_ids if (parent := parents.get(f)) is not None
    }
    siblings = {
        field_id
        for field_id, parent in parents.items()
        if parent is not None and parent in interest_parents and field_id not in interest_field_ids
    }
    adjacent_field_ids = siblings | (interest_parents - interest_field_ids)

    suppressed_fields = suppressed_field_ids(session, user, now)
    suppressed_authors = suppressed_author_keys(session, user, now)
    reinjectable = reinjectable_paper_ids(session, user, now)

    # Field-level overlap with what the user already saved. This is honestly a proxy for
    # the embedding similarity of Phase 3, and the reason label is only attached when the
    # overlap is on the primary field, so the claim stays defensible.
    saved_primary_fields = set(
        session.execute(
            select(Paper.primary_field_id)
            .join(SavedPaper, SavedPaper.paper_id == Paper.id)
            .where(SavedPaper.user_id == user.id)
        ).scalars()
    ) - {None}

    papers = list(session.execute(_candidate_query(user, reinjectable)).scalars())

    now_year = now.year
    candidates: dict[str, list[Candidate]] = {"matched": [], "adjacent": [], "exploration": []}
    for paper in papers:
        paper_fields = significant_fields(paper)
        if paper_fields & suppressed_fields:
            continue
        author_key = _first_author_key(paper)
        if author_key and author_key in suppressed_authors:
            continue

        pool = _pool_for(paper, interest_field_ids, adjacent_field_ids)
        interest = _interest_strength(paper, interests)
        freshness = _freshness(paper.year, now_year)
        difficulty = _difficulty_fit(paper, user)
        quality = _quality_proxy(paper)

        # Weights inside a pool. The pool split already handled the 70/20/10 mix, so these
        # only decide ordering among comparable candidates.
        score = 0.40 * interest + 0.20 * difficulty + 0.20 * freshness + 0.20 * quality
        if pool == "exploration":
            # Deterministic jitter keyed by paper and snapshot: exploration should not
            # always surface the same handful of papers, but paging must stay stable.
            digest = hashlib.sha256(f"{seed}:{paper.canonical_id}".encode()).digest()
            score += (digest[0] / 255.0) * 0.30

        reasons: list[str] = []
        if pool == "matched":
            reasons.append("matches_field")
        elif pool == "adjacent":
            reasons.append("adjacent_field")
        if paper.primary_field_id in saved_primary_fields:
            reasons.append("similar_to_saved")
        if paper.year >= now_year - 1:
            reasons.append("recent")
        if "classic" in (paper.paper_types or []) or paper.year <= now_year - 8:
            reasons.append("foundational")
        if not reasons:
            # Exploration with no other signal still needs a truthful label.
            reasons.append("adjacent_field" if pool == "adjacent" else "matches_field")

        candidates[pool].append(
            Candidate(
                paper=paper,
                pool=pool,
                score=score,
                reasons=reasons,
                breakdown={
                    "interest": round(interest, 4),
                    "difficulty": round(difficulty, 4),
                    "freshness": round(freshness, 4),
                    "quality": round(quality, 4),
                },
            )
        )

    for pool_items in candidates.values():
        pool_items.sort(key=lambda c: (-c.score, c.paper.canonical_id))
        # Bound the work per request. Truncating each pool by score is independent of the
        # requested page, so it does not disturb the prefix stability paging relies on.
        del pool_items[MAX_CANDIDATES_PER_POOL:]

    total = sum(len(v) for v in candidates.values())

    recent_fields = [
        row
        for row in session.execute(
            select(Paper.primary_field_id)
            .join(Impression, Impression.paper_id == Paper.id)
            .where(Impression.user_id == user.id)
            .order_by(Impression.shown_at.desc())
            .limit(DIVERSITY_WINDOW)
        ).scalars()
        if row
    ]

    # The whole sequence is built every request and then sliced, rather than being built
    # only up to `offset + limit`: a sequence truncated to the page length would order its
    # tail differently and could re-serve a card the client already saw.
    snapshot = _sequence(candidates, list(reversed(recent_fields)))

    page = snapshot[offset : offset + limit]
    has_more = len(snapshot) > offset + limit
    next_cursor = (
        FeedCursor(seed=seed, offset=offset + limit).encode() if has_more and page else None
    )

    return FeedPage(
        items=page,
        next_cursor=next_cursor,
        degraded=degraded,
        candidate_count=total,
    )


def reason_text(reasons: list[str], locale: str) -> str:
    """Short human sentence for the card (spec section 6: 短く説明可能であること)."""
    ja = {
        "matches_field": "選んだ分野に一致します",
        "adjacent_field": "隣接分野からの提案です",
        "exploration": "まだ見ていない分野です",
        "similar_to_saved": "保存した論文と近い分野です",
        "recent": "最近の研究です",
        "foundational": "基礎的・古典的な研究です",
    }
    en = {
        "matches_field": "Matches a field you chose",
        "adjacent_field": "From an adjacent field",
        "exploration": "A field you have not explored",
        "similar_to_saved": "Close to something you saved",
        "recent": "Recent work",
        "foundational": "Foundational or classic work",
    }
    table = ja if locale.startswith("ja") else en
    parts = [table[r] for r in reasons if r in table]
    if not parts:
        return ""
    separator = "。" if table is ja else ". "
    return separator.join(parts[:2]) + ("。" if table is ja else ".")


__all__ = [
    "POOL_ALLOCATION",
    "Candidate",
    "FeedCursor",
    "FeedPage",
    "build_feed",
    "reason_text",
    "reinjectable_paper_ids",
    "suppressed_author_keys",
    "suppressed_field_ids",
]
