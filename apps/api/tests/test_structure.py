"""Heuristic abstract structure detection (spec sections 8, 30)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from papermatch_api.services.structure import ORDER, agreement, classify

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "papers.sample.json"


def sections(abstract: str) -> list[str]:
    return [segment.section for segment in classify(abstract)]


def test_a_conventional_abstract_is_labelled_in_order() -> None:
    abstract = (
        "Weak lensing measures the projected matter distribution. "
        "However, reported values differ between surveys by more than the quoted errors. "
        "We reanalyse the shear catalogue with a forward-modelled likelihood. "
        "We obtain a reduced tension of 1.7 sigma. "
        "This suggests the discrepancy is not purely systematic."
    )
    assert sections(abstract) == ["background", "problem", "method", "result", "significance"]


def test_offsets_point_at_the_original_text_and_never_modify_it() -> None:
    abstract = "First one. Second one. Third one."
    for segment in classify(abstract):
        excerpt = abstract[segment.start : segment.end]
        assert excerpt.strip() == excerpt, "offsets should not include the leading gap"
        assert excerpt in abstract


def test_labels_are_stamped_heuristic_not_ai() -> None:
    """Spec section 8: the label must say how it was produced.

    Calling a cue-phrase pass "ai" would claim more for it than a reader should trust.
    """
    for segment in classify("We propose a method. We obtain a result."):
        assert segment.detected_by == "heuristic"


def test_confidence_is_never_presented_as_certainty() -> None:
    for segment in classify("We propose a method. We obtain a result."):
        assert 0.0 < segment.confidence <= 0.85


def test_a_cue_supported_label_is_more_confident_than_a_positional_guess() -> None:
    cued = classify("We propose a new estimator.")[0]
    bare = classify("The quantity varies.")[0]
    assert cued.confidence > bare.confidence


def test_periods_inside_maths_do_not_split_a_sentence() -> None:
    abstract = r"The gap closes at $\theta_c = 1.09^{\circ}$. We obtain a clean signature."
    segments = classify(abstract)
    assert len(segments) == 2
    assert abstract[segments[0].start : segments[0].end].endswith("$.")


def test_abbreviations_do_not_split_a_sentence() -> None:
    assert len(classify("We follow Ref. 3 throughout the paper.")) == 1


def test_the_sequence_does_not_run_backwards() -> None:
    """Abstracts move forwards through the roles; a late cue must not rewind the whole
    thing to Background."""
    abstract = (
        "We propose a new estimator. "
        "We obtain a variance reduction of 30%. "
        "Gauge theories describe the standard model. "
        "This suggests a broader application."
    )
    indices = [ORDER.index(s) for s in sections(abstract)]
    assert all(b >= a - 1 for a, b in itertools.pairwise(indices))


def test_a_single_sentence_abstract_is_handled() -> None:
    assert len(classify("A short abstract with no structure at all.")) == 1


@pytest.mark.parametrize("abstract", ["", "   ", "\n\n"])
def test_empty_input_produces_nothing(abstract: str) -> None:
    assert classify(abstract) == []


def test_every_sentence_gets_exactly_one_label() -> None:
    abstract = "One. Two. Three. Four. Five. Six."
    segments = classify(abstract)
    assert len(segments) == 6
    assert all(s.section in ORDER for s in segments)
    # Spans must not overlap, or the card would highlight a sentence twice.
    for a, b in itertools.pairwise(segments):
        assert a.end <= b.start


def test_it_beats_a_positional_baseline_on_the_fixture_corpus() -> None:
    """The corpus carries ``detected_by='source'`` ground truth (DECISIONS.md D-005).

    The floor is deliberately modest — this is cue matching, not a model. What the test
    pins down is that the classifier is meaningfully better than guessing by position
    alone, and that a future model has a number to beat.
    """
    document = json.loads(FIXTURES.read_text(encoding="utf-8"))
    papers = document["papers"]

    scores: list[float] = []
    for paper in papers:
        truth = [(s["start"], s["end"], s["section"]) for s in paper["abstractSegments"]]
        scores.append(agreement(classify(paper["abstract"]), truth))

    mean = sum(scores) / len(scores)
    perfect = sum(1 for s in scores if s == 1.0)
    # Measured at 0.89 mean / 34 of 60 perfect when written. The floors sit below that so
    # ordinary cue tuning does not trip them, but a real regression does.
    assert mean >= 0.80, f"agreement with the corpus dropped to {mean:.2f}"
    assert perfect >= 25, f"only {perfect} abstracts were labelled correctly end to end"
