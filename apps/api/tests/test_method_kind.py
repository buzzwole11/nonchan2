"""Theory / experiment / review classification (spec sections 16, 18).

The test that matters most here is the one about abstaining. A classifier that always
answers is easy to write and useless to trust, and the feed nudge built on it would then
confidently boost the wrong papers.
"""

from __future__ import annotations

import pytest

from papermatch_api.services.method_kind import (
    EXPERIMENTAL_CUES,
    THEORETICAL_CUES,
    classify_method_kind,
    method_kind_scores,
)


@pytest.mark.parametrize(
    ("name", "cues"), [("experimental", EXPERIMENTAL_CUES), ("theoretical", THEORETICAL_CUES)]
)
def test_no_cue_is_a_substring_of_another(name: str, cues: tuple[tuple[str, float], ...]) -> None:
    """Matching is by substring, so an overlapping pair scores twice for one phrase.

    Found by a genuinely mixed abstract coming out `theoretical`: `perturbative` and
    `non-perturbative` were both listed, so one word was worth 1.8.
    """
    phrases = [phrase for phrase, _ in cues]
    for phrase in phrases:
        others = [p for p in phrases if p != phrase and phrase in p]
        assert not others, f"{name}: {phrase!r} is contained in {others}"


def test_an_abstract_about_measuring_things_is_experimental() -> None:
    kind = classify_method_kind(
        "Thermal Transport in Layered Antiferromagnets",
        "We measured the thermal conductivity of thin films grown by molecular beam epitaxy. "
        "Samples were cooled to 4 K and the apparatus was calibrated against a reference "
        "specimen before each run.",
    )
    assert kind == "experimental"


def test_an_abstract_about_proving_things_is_theoretical() -> None:
    kind = classify_method_kind(
        "Bounds on Entanglement Growth",
        "We prove an upper bound on the rate of entanglement growth in local Hamiltonian "
        "systems. The proof proceeds by a perturbative expansion and the theorem holds for "
        "all bounded-degree interaction graphs.",
    )
    assert kind == "theoretical"


def test_an_abstract_that_does_not_say_gets_no_label() -> None:
    """Not determined is a first-class answer. A paper carrying neither label means the
    abstract did not say, never that it is neither."""
    assert (
        classify_method_kind(
            "On a Class of Transport Phenomena",
            "This work considers transport in disordered media and discusses several "
            "consequences for the field.",
        )
        is None
    )


def test_a_paper_doing_both_is_not_forced_into_one() -> None:
    """Genuinely mixed evidence is the case a forced choice gets wrong half the time."""
    assert (
        classify_method_kind(
            "Measured and Predicted Conductance Plateaus",
            "We derive a closed form for the conductance and measure it in fabricated "
            "nanowire devices. The analytical result and the measurements agree.",
        )
        is None
    )


def test_a_survey_is_a_review_even_when_it_is_full_of_experiments() -> None:
    """Section 16 balances 理論 / 実験 / レビュー as three, not two."""
    kind = classify_method_kind(
        "Cold Atom Simulators: A Review",
        "We review two decades of measurements from cold atom experiments, covering the "
        "apparatus, the detectors and the calibration procedures used across the field.",
    )
    assert kind == "review"


def test_subject_matter_alone_decides_nothing() -> None:
    """The cues are about what was done. If they drifted into topic words the classifier
    would quietly become a field classifier wearing the wrong label."""
    experimental, theoretical = method_kind_scores(
        "Quantum Gravity and Black Hole Thermodynamics",
        "Quantum effects near the horizon of a black hole are considered in the context of "
        "quantum gravity and quantum field theory.",
    )
    assert experimental == theoretical == 0.0


def test_maths_is_not_read_as_prose() -> None:
    """An unmasked `\\text{sample}` inside a formula would count as if the author had
    written it in a sentence."""
    plain = method_kind_scores("T", "This considers the behaviour of the system.")
    with_maths = method_kind_scores(
        "T", "This considers the behaviour of the system $\\text{sample} = \\theorem_1$."
    )
    assert plain == with_maths


def test_a_repeated_cue_does_not_decide_on_its_own() -> None:
    once = method_kind_scores("T", "The sample was prepared.")
    many = method_kind_scores("T", "The sample was prepared. The sample. The sample. Sample.")
    assert once == many
