"""Candidate scoring (spec section 16).

Section 16 gives the shape directly:

    interest match + quality + freshness + difficulty fit + exploration bonus
    - recent similarity - repeated author penalty

Three things about how that is implemented here.

**The score never reaches the reader.** Section 16 asks for 推薦理由の文言, and section 3
puts trust in provenance rather than in a number. A single number invites the reader to
optimise against it, and it cannot be argued with — "0.72" says nothing about why. So the
components are computed, the top ones are turned into sentences, and the number stays
server-side. `explain()` is what the UI gets.

**The penalties subtract, they do not exclude.** Section 16 is explicit that negative
feedback is 「今回は見送る」 and not 「嫌い」. A paper by an author the reader has just seen
twice is pushed down the queue, not removed from it — a hard filter would make the feed
narrow in a way nobody chose and nobody can undo.

**Difficulty fit is symmetric.** A paper far *below* the reader's level is as poor a match
as one far above it. Scoring only the "too hard" direction would slowly fill the feed with
things they already know.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from papermatch_api.providers.local_embedding import cosine

__all__ = [
    "WEIGHTS",
    "ScoreInput",
    "ScoredCandidate",
    "difficulty_fit",
    "freshness",
    "score_candidate",
]

#: How much each component can move the total. Section 16 lists the components but not
#: their sizes; these are chosen so that no single one can dominate — interest is the
#: largest, and the two penalties together can outweigh it, which is what lets diversity
#: control actually change the order rather than just re-rank within a topic.
WEIGHTS = {
    "interest": 1.0,
    "quality": 0.35,
    "freshness": 0.30,
    "difficulty": 0.45,
    "exploration": 0.25,
    "similarity_penalty": 0.80,
    "author_penalty": 0.55,
}

#: Levels the onboarding offers, in order, so "two steps harder" is a number.
ENGLISH_ORDER = ("beginner", "intermediate", "advanced", "native_like")
MATH_ORDER = ("level_0", "level_1", "level_2", "level_3", "level_4")

#: A paper stops counting as new after this. Section 16 wants freshness, not a news feed —
#: two years is roughly how long a preprint stays "current" in the fields this app covers.
FRESHNESS_HORIZON_YEARS = 2.0


@dataclass
class ScoreInput:
    """Everything one candidate is judged on."""

    paper_id: str
    year: int
    primary_field_id: str | None
    field_weights: dict[str, float]
    author_names: tuple[str, ...]
    english_level: str
    math_density: float
    open_access: str
    citation_count: int | None = None
    embedding: list[float] = field(default_factory=list)
    #: Which pool the mixer drew it from, so exploration is credited where it is due.
    pool: str = "matched"


@dataclass
class ReaderContext:
    """What the reader has told us and what they have just seen."""

    interest_field_ids: frozenset[str] = frozenset()
    interest_parent_ids: frozenset[str] = frozenset()
    english_level: str = "intermediate"
    math_level: str = "level_2"
    #: Embeddings of the last cards shown, newest first (spec section 16: 直近20件).
    recent_embeddings: tuple[list[float], ...] = ()
    #: How many of the recent cards each author appeared on.
    recent_author_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoredCandidate:
    paper_id: str
    total: float
    components: dict[str, float]

    def explain(self) -> list[str]:
        """Reason keys, strongest first — never the number.

        Only components that actually moved the result are named. A reason list that
        recites every term for every paper says nothing about *this* paper.
        """
        ordered = sorted(
            ((name, value) for name, value in self.components.items() if abs(value) >= 0.05),
            key=lambda pair: abs(pair[1]),
            reverse=True,
        )
        return [name for name, _ in ordered[:3]]


def _significant(weights: dict[str, float], threshold: float = 0.15) -> set[str]:
    """Fields a paper is actually about, not ones it brushes against."""
    return {field_id for field_id, weight in weights.items() if weight >= threshold}


def interest_match(candidate: ScoreInput, reader: ReaderContext) -> float:
    """1.0 for a chosen field, 0.5 for its parent, 0 otherwise.

    The parent credit is what makes the 20% adjacent pool mean something: a reader who
    chose `hep-th` should find `cond-mat` more interesting than `cs.CL`, and without a
    partial credit the two would score identically at zero.
    """
    fields = _significant(candidate.field_weights)
    if candidate.primary_field_id is not None:
        fields.add(candidate.primary_field_id)
    if fields & reader.interest_field_ids:
        return 1.0
    if fields & reader.interest_parent_ids:
        return 0.5
    return 0.0


def quality(candidate: ScoreInput) -> float:
    """A deliberately weak signal.

    Citations reward age and fashion, so they are damped hard and capped. Open access
    counts because a paper the reader cannot open is a worse recommendation regardless of
    how good it is — that is about the reader's situation, not the paper's merit.
    """
    from math import log1p

    cited = (
        0.0 if candidate.citation_count is None else min(1.0, log1p(candidate.citation_count) / 6.0)
    )
    openness = 0.0 if candidate.open_access == "closed" else 1.0
    return 0.6 * cited + 0.4 * openness


def freshness(candidate: ScoreInput, *, now: datetime | None = None) -> float:
    """1.0 this year, falling linearly to 0 at the horizon, never negative."""
    current = (now or datetime.now(tz=UTC)).year
    age = current - candidate.year
    if age <= 0:
        return 1.0
    return max(0.0, 1.0 - age / FRESHNESS_HORIZON_YEARS)


def difficulty_fit(candidate: ScoreInput, reader: ReaderContext) -> float:
    """How close the paper is to the reader's level, in both directions.

    Symmetric on purpose: a paper two steps below the reader is as poor a match as one two
    steps above. Scoring only the "too hard" side would fill the feed with things they
    already know, which is the failure mode this app exists to avoid.
    """
    try:
        want_english = ENGLISH_ORDER.index(reader.english_level)
        has_english = ENGLISH_ORDER.index(candidate.english_level)
    except ValueError:
        return 0.5

    english_gap = abs(want_english - has_english) / (len(ENGLISH_ORDER) - 1)

    # Maths density is a continuous number; the reader's tolerance is a level. Map the
    # level onto the density scale the corpus actually uses rather than inventing units.
    tolerated = {"level_0": 0.0, "level_1": 1.5, "level_2": 3.0, "level_3": 5.0, "level_4": 8.0}
    want_math = tolerated.get(reader.math_level, 3.0)
    math_gap = min(1.0, abs(candidate.math_density - want_math) / 8.0)

    return max(0.0, 1.0 - 0.6 * english_gap - 0.4 * math_gap)


def exploration_bonus(candidate: ScoreInput) -> float:
    """Credit for being the reason the exploration pool exists.

    Without it the mixer would place an exploration card and the scorer would immediately
    rank it last, so the 10% slot would always be filled by whatever unfamiliar paper
    happened to score least badly — a lottery rather than a choice.
    """
    return {"exploration": 1.0, "adjacent": 0.4}.get(candidate.pool, 0.0)


def similarity_penalty(candidate: ScoreInput, reader: ReaderContext) -> float:
    """How much this repeats what the reader has just seen (section 16: 直近20件).

    The *maximum* similarity, not the mean. One near-duplicate among twenty is the thing
    worth suppressing, and averaging would bury it under nineteen unrelated cards.
    """
    if not candidate.embedding or not reader.recent_embeddings:
        return 0.0
    return max(
        (max(0.0, cosine(candidate.embedding, recent)) for recent in reader.recent_embeddings),
        default=0.0,
    )


def author_penalty(candidate: ScoreInput, reader: ReaderContext) -> float:
    """Suppress a run by the same author, without hiding them.

    Saturating rather than linear: the difference between seeing an author once and twice
    matters, the difference between five and six does not, and an unbounded penalty would
    amount to a ban nobody asked for.
    """
    if not candidate.author_names:
        return 0.0
    seen = max(
        (reader.recent_author_counts.get(name, 0) for name in candidate.author_names), default=0
    )
    if seen <= 0:
        return 0.0
    return min(1.0, seen / 3.0)


def score_candidate(
    candidate: ScoreInput, reader: ReaderContext, *, now: datetime | None = None
) -> ScoredCandidate:
    components = {
        "interest": WEIGHTS["interest"] * interest_match(candidate, reader),
        "quality": WEIGHTS["quality"] * quality(candidate),
        "freshness": WEIGHTS["freshness"] * freshness(candidate, now=now),
        "difficulty": WEIGHTS["difficulty"] * difficulty_fit(candidate, reader),
        "exploration": WEIGHTS["exploration"] * exploration_bonus(candidate),
        "similarity_penalty": -WEIGHTS["similarity_penalty"]
        * similarity_penalty(candidate, reader),
        "author_penalty": -WEIGHTS["author_penalty"] * author_penalty(candidate, reader),
    }
    return ScoredCandidate(
        paper_id=candidate.paper_id,
        total=sum(components.values()),
        components=components,
    )
