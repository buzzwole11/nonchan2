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

**There is no exploration bonus, despite section 16 listing one.** Under D-017 the 70/20/10
mix is a slot allocation: candidates are partitioned into pools and each pool is ranked
separately. A term that depends only on which pool a candidate is in is therefore constant
across everything it is compared against, and cannot move a single card. Keeping it would
have meant carrying a weight, a test and a line of documentation for arithmetic that
provably does nothing. What the exploration pool actually needs — not always surfacing the
same handful of papers — is a tie-break inside that pool, and that lives in `feed.py` where
the paging seed it depends on lives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import log1p

from papermatch_api.providers.local_embedding import cosine

__all__ = [
    "SIGNIFICANT_FIELD_WEIGHT",
    "WEIGHTS",
    "ReaderContext",
    "ScoreInput",
    "ScoredCandidate",
    "difficulty_fit",
    "freshness",
    "interest_match",
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
    "similarity_penalty": 0.80,
    "author_penalty": 0.55,
}

#: Minimum field weight for a paper to count as being *about* that field. Below this the
#: tag is incidental: a machine-learning paper carrying a 0.05 tag for high-energy theory
#: is not a high-energy theory paper, and treating it as one would put almost everything in
#: the matched pool and quietly destroy the 70/20/10 mix.
SIGNIFICANT_FIELD_WEIGHT = 0.15

#: What an adjacent field inherits from the reader's declared interests. Half, because the
#: reader did not choose it — but not zero, or the 20% adjacent slot would be filled by
#: whichever unchosen paper happened to score least badly on everything else.
ADJACENT_CREDIT = 0.5

#: Floor on the field weight used in the interest term. A paper that is only partly about a
#: chosen field is still about it; without a floor, a 0.2 weight would score a chosen field
#: below an adjacent one that happened to be the paper's main subject.
MIN_FIELD_WEIGHT = 0.2

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
    #: A named venue and a resolvable identifier are what `quality` has to work with in
    #: this corpus; citations are optional because no provider we ingest from supplies them.
    has_venue: bool = False
    has_resolvable_id: bool = False
    citation_count: int | None = None
    embedding: list[float] = field(default_factory=list)


@dataclass
class ReaderContext:
    """What the reader has told us and what they have just seen."""

    #: Field id → how strongly the reader said they care (0..1). Membership *and* degree:
    #: onboarding lets a reader weight their interests, and a scorer that only knew the set
    #: would give every paper in the matched pool the same interest term, leaving the
    #: largest weight in the model unable to order anything.
    interest_strengths: dict[str, float] = field(default_factory=dict)
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


def subject_weights(candidate: ScoreInput) -> dict[str, float]:
    """The fields a paper is actually about, with how much of it they account for.

    The primary field is always included even if it carries no explicit weight — it is the
    provider's own answer to "what is this paper", and dropping it would leave papers whose
    only classification is the primary field with no subject at all.
    """
    weights = {
        field_id: weight
        for field_id, weight in candidate.field_weights.items()
        if weight >= SIGNIFICANT_FIELD_WEIGHT
    }
    if candidate.primary_field_id is not None:
        weights.setdefault(candidate.primary_field_id, ADJACENT_CREDIT)
    return weights


def _strength(reader: ReaderContext, field_id: str) -> float:
    declared = reader.interest_strengths.get(field_id)
    if declared is not None:
        return declared
    return ADJACENT_CREDIT if field_id in reader.interest_parent_ids else 0.0


def interest_match(candidate: ScoreInput, reader: ReaderContext) -> float:
    """How much of this paper is about something the reader asked for.

    One formula covers both cases: the reader's declared strength for a chosen field, or a
    half-credit inherited by an adjacent one, multiplied by how much of the paper that field
    accounts for. The adjacent credit is what makes the 20% pool mean something — a reader
    who chose `hep-th` should find `cond-mat` more interesting than `cs.CL`, and without
    partial credit the two would score identically at zero.

    The multiplication by field weight is what keeps this term useful *inside* a pool. Every
    card in the matched pool matches by definition, so a term that returned 1.0 for all of
    them would leave the largest weight in the model ordering nothing.
    """
    return min(
        1.0,
        max(
            (
                _strength(reader, field_id) * max(MIN_FIELD_WEIGHT, weight)
                for field_id, weight in subject_weights(candidate).items()
            ),
            default=0.0,
        ),
    )


def quality(candidate: ScoreInput) -> float:
    """A deliberately weak signal, and not a judgement of the work.

    Section 2 is explicit that this is not a peer-review-quality app, so nothing here claims
    to measure merit. It prefers records we can actually show well: open access, a named
    venue, a resolvable identifier. Open access counts because a paper the reader cannot
    open is a worse recommendation regardless of how good it is — that is about the reader's
    situation, not the paper's.

    Citations are included when a provider supplies them, damped hard and capped, because
    they reward age and fashion at least as much as they reward substance.
    """
    openness = 0.0 if candidate.open_access in {"closed", "unknown"} else 1.0
    findable = 0.5 * float(candidate.has_venue) + 0.5 * float(candidate.has_resolvable_id)
    if candidate.citation_count is None:
        return 0.6 * openness + 0.4 * findable
    cited = min(1.0, log1p(candidate.citation_count) / 6.0)
    return 0.4 * openness + 0.3 * findable + 0.3 * cited


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

    if reader.math_level == "level_0":
        # Section 18 reads level 0 as 数式を表示しない, which is a statement about what the
        # reader wants to see rather than a preference to be traded off. A formula-heavy
        # paper gets nothing here — but it is still scored, because a hard filter would
        # empty the deck for a reader who chose a mathematical field and level 0 together.
        math_fit = 1.0 if candidate.math_density <= 0.5 else 0.0
    else:
        # Maths density is a continuous number; the reader's tolerance is a level. Map the
        # level onto the density scale the corpus actually uses rather than inventing units.
        tolerated = {"level_1": 1.5, "level_2": 3.0, "level_3": 5.0, "level_4": 8.0}
        want_math = tolerated.get(reader.math_level, 3.0)
        math_fit = 1.0 - min(1.0, abs(candidate.math_density - want_math) / 8.0)

    return max(0.0, 1.0 - 0.6 * english_gap - 0.4 * (1.0 - math_fit))


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
        "similarity_penalty": -WEIGHTS["similarity_penalty"]
        * similarity_penalty(candidate, reader),
        "author_penalty": -WEIGHTS["author_penalty"] * author_penalty(candidate, reader),
    }
    return ScoredCandidate(
        paper_id=candidate.paper_id,
        total=sum(components.values()),
        components=components,
    )
