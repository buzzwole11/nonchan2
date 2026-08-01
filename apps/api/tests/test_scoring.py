"""Candidate scoring (spec section 16).

The tests that matter are the ones about what the score must *not* do: reach the reader,
exclude a paper outright, or reward only the "too hard" direction of difficulty.
"""

from __future__ import annotations

from datetime import UTC, datetime

from papermatch_api.providers.local_embedding import embed
from papermatch_api.services.scoring import (
    ReaderContext,
    ScoreInput,
    difficulty_fit,
    freshness,
    score_candidate,
)

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def candidate(**overrides: object) -> ScoreInput:
    base: dict[str, object] = {
        "paper_id": "p1",
        "year": 2026,
        "primary_field_id": "hep-th",
        "field_weights": {"hep-th": 0.7, "physics": 0.2},
        "author_names": ("A. Fujimoto",),
        "english_level": "intermediate",
        "math_density": 3.0,
        "open_access": "green",
        "citation_count": 12,
        "embedding": [],
        "pool": "matched",
    }
    base.update(overrides)
    return ScoreInput(**base)  # type: ignore[arg-type]


def reader(**overrides: object) -> ReaderContext:
    base: dict[str, object] = {
        "interest_field_ids": frozenset({"hep-th"}),
        "interest_parent_ids": frozenset({"physics"}),
        "english_level": "intermediate",
        "math_level": "level_2",
        "recent_embeddings": (),
        "recent_author_counts": {},
    }
    base.update(overrides)
    return ReaderContext(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------------- interest and pools


def test_a_chosen_field_scores_above_an_adjacent_one() -> None:
    chosen = score_candidate(candidate(), reader(), now=NOW)
    adjacent = score_candidate(
        candidate(primary_field_id="cond-mat", field_weights={"cond-mat": 0.7, "physics": 0.2}),
        reader(),
        now=NOW,
    )
    assert chosen.components["interest"] > adjacent.components["interest"] > 0


def test_an_unrelated_field_earns_no_interest_but_is_still_scored() -> None:
    """Section 16 treats a miss as 「今回は見送る」, not as a filter."""
    unrelated = score_candidate(
        candidate(primary_field_id="cs.CL", field_weights={"cs.CL": 0.8}), reader(), now=NOW
    )
    assert unrelated.components["interest"] == 0.0
    assert unrelated.total > 0, "it should still be rankable, not excluded"


def test_an_incidental_field_tag_does_not_count_as_a_match() -> None:
    """A 0.05 weight is a mention, not a subject."""
    incidental = score_candidate(
        candidate(primary_field_id="cs.CL", field_weights={"cs.CL": 0.9, "hep-th": 0.05}),
        reader(),
        now=NOW,
    )
    assert incidental.components["interest"] == 0.0


def test_the_exploration_pool_is_credited_for_being_unfamiliar() -> None:
    """Otherwise the scorer immediately ranks every exploration card last and the 10%
    slot becomes a lottery."""
    explore = score_candidate(
        candidate(primary_field_id="math.NT", field_weights={"math.NT": 0.9}, pool="exploration"),
        reader(),
        now=NOW,
    )
    assert explore.components["exploration"] > 0


# ------------------------------------------------------------------------- difficulty


def test_difficulty_fit_is_symmetric() -> None:
    """A paper far below the reader is as poor a match as one far above.

    Scoring only the hard direction slowly fills the feed with what they already know.
    """
    too_hard = difficulty_fit(candidate(english_level="native_like"), reader())
    too_easy = difficulty_fit(candidate(english_level="beginner"), reader())
    just_right = difficulty_fit(candidate(english_level="intermediate"), reader())

    assert just_right > too_hard
    assert just_right > too_easy


def test_maths_density_moves_the_fit_towards_the_reader_setting() -> None:
    dense = difficulty_fit(candidate(math_density=9.0), reader(math_level="level_0"))
    sparse = difficulty_fit(candidate(math_density=0.2), reader(math_level="level_0"))
    assert sparse > dense


def test_an_unknown_level_does_not_crash_the_score() -> None:
    assert 0.0 <= difficulty_fit(candidate(english_level="???"), reader()) <= 1.0


# -------------------------------------------------------------------------- freshness


def test_freshness_falls_with_age_and_stops_at_zero() -> None:
    assert freshness(candidate(year=2026), now=NOW) == 1.0
    assert 0 < freshness(candidate(year=2025), now=NOW) < 1
    assert freshness(candidate(year=2010), now=NOW) == 0.0


# ------------------------------------------------------------------------- penalties


def test_a_near_duplicate_of_a_recent_card_is_pushed_down() -> None:
    text = "Topological invariants classify insulating phases of matter."
    seen = embed(text)
    penalised = score_candidate(
        candidate(embedding=embed(text)), reader(recent_embeddings=(seen,)), now=NOW
    )
    fresh = score_candidate(
        candidate(embedding=embed("Sample-efficient reinforcement learning with a learned model.")),
        reader(recent_embeddings=(seen,)),
        now=NOW,
    )
    assert penalised.components["similarity_penalty"] < fresh.components["similarity_penalty"]
    assert penalised.total < fresh.total


def test_the_similarity_penalty_uses_the_worst_match_not_the_average() -> None:
    """One near-duplicate among twenty is the thing worth suppressing; averaging buries it."""
    duplicate = embed("Topological invariants classify insulating phases.")
    noise = tuple(embed(f"unrelated subject number {i} about linguistics") for i in range(19))
    scored = score_candidate(
        candidate(embedding=duplicate),
        reader(recent_embeddings=(*noise, duplicate)),
        now=NOW,
    )
    assert scored.components["similarity_penalty"] < -0.5


def test_a_repeated_author_is_pushed_down_but_never_removed() -> None:
    """Section 16: 否定的フィードバックを「嫌い」と決めつけない."""
    repeated = score_candidate(
        candidate(), reader(recent_author_counts={"A. Fujimoto": 3}), now=NOW
    )
    first_time = score_candidate(candidate(), reader(), now=NOW)

    assert repeated.total < first_time.total
    assert repeated.components["author_penalty"] < 0
    assert repeated.total > -10, "a penalty, not an exclusion"


def test_the_author_penalty_saturates() -> None:
    three = score_candidate(candidate(), reader(recent_author_counts={"A. Fujimoto": 3}), now=NOW)
    ten = score_candidate(candidate(), reader(recent_author_counts={"A. Fujimoto": 10}), now=NOW)
    assert three.components["author_penalty"] == ten.components["author_penalty"]


def test_penalties_can_outweigh_a_perfect_interest_match() -> None:
    """Otherwise diversity control only re-orders within a topic instead of breaking it."""
    text = "Holographic entanglement entropy in deformed conformal backgrounds."
    smothered = score_candidate(
        candidate(embedding=embed(text)),
        reader(recent_embeddings=(embed(text),), recent_author_counts={"A. Fujimoto": 3}),
        now=NOW,
    )
    plain = score_candidate(
        candidate(primary_field_id="cs.CL", field_weights={"cs.CL": 0.9}), reader(), now=NOW
    )
    assert smothered.total < plain.total


# ---------------------------------------------------------------- what the reader sees


def test_the_reasons_are_names_never_the_number() -> None:
    """Section 3 puts trust in provenance, not in a score. A number invites optimising
    against it and cannot be argued with."""
    scored = score_candidate(candidate(), reader(), now=NOW)
    reasons = scored.explain()
    assert reasons
    assert all(isinstance(r, str) for r in reasons)
    assert all(not any(ch.isdigit() for ch in r) for r in reasons)


def test_only_components_that_moved_the_result_are_named() -> None:
    """Reciting every term for every paper says nothing about this paper."""
    scored = score_candidate(
        candidate(primary_field_id="cs.CL", field_weights={"cs.CL": 0.9}, citation_count=None),
        reader(),
        now=NOW,
    )
    assert "interest" not in scored.explain()


def test_the_strongest_reason_comes_first() -> None:
    scored = score_candidate(candidate(), reader(), now=NOW)
    assert scored.explain()[0] == "interest"


def test_at_most_three_reasons() -> None:
    """A card that lists seven reasons is a card nobody reads."""
    scored = score_candidate(candidate(), reader(recent_author_counts={"A. Fujimoto": 2}), now=NOW)
    assert len(scored.explain()) <= 3


def test_the_total_is_reproducible() -> None:
    """A recommendation that changes on re-run is one nobody can debug."""
    first = score_candidate(
        candidate(embedding=embed("quantum error correction")), reader(), now=NOW
    )
    second = score_candidate(
        candidate(embedding=embed("quantum error correction")), reader(), now=NOW
    )
    assert first.total == second.total
