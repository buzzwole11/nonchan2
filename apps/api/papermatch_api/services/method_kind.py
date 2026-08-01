"""Is this paper theoretical or experimental? (spec sections 16, 18)

Section 16 asks the feed to balance 理論 / 実験 / レビュー and offers the reader a
「実験系を増やす」 button. Neither arXiv nor OpenAlex publishes that distinction, so
without something here the button would be one that cannot do anything.

**This is a rule-based classifier and it says so.** The labels it produces go into
``paper_types`` alongside `preprint` and `classic`, and the vocabulary note records how
they got there. Calling cue matching "AI" would overstate what a reader should trust it
for — the same reasoning as the abstract structure classifier (DECISIONS.md D-022).

**It abstains, and that is the point.** A great many papers are genuinely both, or say
nothing either way in 200 words, and the honest output for those is no label at all. A
classifier forced to choose would be right about half the time on the hard cases and the
feed would then confidently boost the wrong papers. So a label is only attached when one
side clearly outweighs the other; a paper carrying neither label means *not determined*,
never *neither*. The feedback nudge in `services/feed.py` reads it that way: it lifts the
papers known to be experimental rather than pushing down everything else.

The cue lists are deliberately about **what was done**, not about subject matter. "Quantum"
is not evidence of anything; "we measured", "our apparatus", "the sample was cooled" are.
That distinction is what keeps this from collapsing into a field classifier.
"""

from __future__ import annotations

import re

from papermatch_api.text.math_placeholders import mask_math

__all__ = ["MARGIN", "classify_method_kind", "method_kind_scores"]

#: Evidence that someone collected data from the world. Weighted by how hard the phrase is
#: to write about a purely theoretical paper.
#:
#: **No cue may be a substring of another in the same list.** Matching is by substring, so
#: an overlapping pair scores twice for one phrase and lets a single word decide the label.
#: Stems are used for that reason — "measurement" covers the plural, "calibrat" covers both
#: the noun and the verb — and ``test_no_cue_is_a_substring_of_another`` holds the line.
EXPERIMENTAL_CUES: tuple[tuple[str, float], ...] = (
    ("we measure", 1.0),
    ("measurement", 0.8),
    ("we observe", 0.7),
    ("observation", 0.6),
    ("apparatus", 1.0),
    ("detector", 0.8),
    ("telescope", 0.9),
    ("spectrometer", 1.0),
    ("microscope", 0.9),
    ("sample", 0.6),
    ("specimen", 0.9),
    ("fabricat", 0.9),
    ("synthesised", 0.8),
    ("synthesized", 0.8),
    # Stems, not conjugations. "we collected" alone missed every abstract written in the
    # present tense, which is most of them — the same slip as `calibration` vs `calibrated`.
    ("we collect", 0.8),
    ("we fit", 0.7),
    ("annotat", 0.7),
    ("held-out", 0.7),
    ("catalogue", 0.7),
    ("data set", 0.5),
    ("dataset", 0.5),
    ("benchmark", 0.5),
    ("experiments on", 0.8),
    ("experimental results", 0.9),
    ("empirical", 0.7),
    ("in situ", 0.8),
    ("calibrat", 0.7),
    ("signal-to-noise", 0.8),
    ("statistical significance", 0.6),
    ("confidence interval", 0.6),
    ("participants", 0.8),
    ("cohort", 0.8),
)

#: Evidence that the work was done with pen and paper. "We prove" is near-decisive; "model"
#: on its own is not, because experimental papers model their instruments. Same
#: no-substrings rule as above — note that `perturbative` deliberately covers
#: `non-perturbative` rather than listing both.
THEORETICAL_CUES: tuple[tuple[str, float], ...] = (
    ("we prove", 1.0),
    ("we show that", 0.5),
    ("theorem", 1.0),
    ("lemma", 1.0),
    ("corollary", 1.0),
    ("proof", 0.9),
    ("we derive", 0.9),
    ("derivation", 0.8),
    ("closed form", 0.8),
    ("analytic", 0.7),
    ("conjecture", 0.9),
    ("ansatz", 0.9),
    ("we formulate", 0.6),
    ("first principles", 0.7),
    ("upper bound", 0.8),
    ("lower bound", 0.8),
    ("asymptotic", 0.7),
    ("perturbative", 0.9),
    ("hamiltonian", 0.7),
    ("lagrangian", 0.8),
    ("we classify", 0.7),
    ("necessary and sufficient", 0.9),
    ("holds for all", 0.8),
)

#: How far ahead one side has to be before a label is attached. Below this the abstract has
#: not said clearly enough, and no label is the honest answer.
MARGIN = 1.2

#: Above this, a review is a review — 「レビュー」 is the third of section 16's three, and a
#: survey of experiments is not itself an experiment.
REVIEW_CUES: tuple[str, ...] = (
    "we review",
    "this review",
    "we survey",
    "this survey",
    "an overview of",
    "lecture notes",
    "tutorial",
)


def _score(text: str, cues: tuple[tuple[str, float], ...]) -> float:
    """Total cue weight, counting each distinct cue once.

    Once rather than per occurrence: an abstract that says "sample" four times is not four
    times more experimental, and rewarding repetition would let a single word decide.
    """
    return sum(weight for phrase, weight in cues if phrase in text)


def method_kind_scores(title: str, abstract: str) -> tuple[float, float]:
    """Raw (experimental, theoretical) evidence, exposed so a miscall can be debugged."""
    # Maths is masked first. A formula full of `\sigma` is not a cue either way, and an
    # unmasked `\text{sample}` inside an equation would count as if the author had written
    # it in prose.
    text = mask_math(f"{title}. {abstract}").masked_text.lower()
    text = re.sub(r"\s+", " ", text)
    return _score(text, EXPERIMENTAL_CUES), _score(text, THEORETICAL_CUES)


def classify_method_kind(title: str, abstract: str) -> str | None:
    """``"experimental"``, ``"theoretical"``, ``"review"``, or ``None`` for *not determined*.

    `None` is a first-class answer, not a failure. See the module docstring.
    """
    text = mask_math(f"{title}. {abstract}").masked_text.lower()
    if any(cue in text for cue in REVIEW_CUES):
        return "review"

    experimental, theoretical = method_kind_scores(title, abstract)
    if experimental - theoretical >= MARGIN:
        return "experimental"
    if theoretical - experimental >= MARGIN:
        return "theoretical"
    return None
