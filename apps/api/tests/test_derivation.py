"""Proposing and checking steps between a paper's equations (spec section 12, steps 6–8).

Two properties matter more than any individual case:

* Nothing here invents an equation. Every endpoint is a line the manuscript contains.
* Nothing is verified by prose. A confident sentence is evidence about what the author
  did, never evidence that it was right.
"""

from __future__ import annotations

from pathlib import Path

from papermatch_api.providers.mock_fulltext import MockFullTextProvider
from papermatch_api.services.derivation import (
    candidates_for,
    classify_relation,
)
from papermatch_api.text.latex_document import parse_document
from tests.conftest import FIXTURES_DIR


def _candidates(canonical_id: str):  # type: ignore[no-untyped-def]
    provider = MockFullTextProvider(Path(FIXTURES_DIR))
    record = provider.fetch_source(canonical_id)
    assert record is not None
    return candidates_for(parse_document(record.body))


# ------------------------------------------------------------------ verification


def test_a_correct_algebraic_step_is_spot_checked() -> None:
    """The substitution check earns `numerically_spot_checked` and no more.

    Not `mechanically_verified`: no dimensional check was supplied and no symbolic
    manipulation was performed, so that label would overstate what actually ran.
    """
    first = _candidates("arXiv:2601.00004")[0]

    assert first.verification_status == "numerically_spot_checked"
    assert "標本点" in first.detail


def test_a_mistranscribed_step_is_rejected_and_says_where() -> None:
    """The fixture's third equation is deliberately wrong.

    A pipeline that only ever passed would tell us nothing about whether the check works.
    """
    wrong = _candidates("arXiv:2601.00004")[1]

    assert wrong.verification_status == "unverified"
    assert "一致しなかった" in wrong.detail


def test_a_verified_step_records_the_range_it_was_checked_on() -> None:
    # The interval is part of the claim: a pass means "on this region", and a later reader
    # must be able to see which one.
    first = _candidates("arXiv:2601.00004")[0]

    assert first.sampled is not None
    assert set(first.sampled) == {"a", "b"}


def test_an_integral_step_is_left_unverified_rather_than_guessed_at() -> None:
    """The Gaussian fixture is all integrals, which the translator refuses.

    Unverified is the correct answer and is hidden by default (section 12) — far better
    than a badge earned by an expression that dropped the integral sign.
    """
    for candidate in _candidates("arXiv:2601.00001"):
        assert candidate.verification_status == "unverified"
        assert "対応範囲外" in candidate.detail


def test_prose_alone_never_verifies_a_step() -> None:
    """Every candidate whose status is above `unverified` ran a numeric check."""
    for candidate in _candidates("arXiv:2601.00001") + _candidates("arXiv:2601.00004"):
        if candidate.verification_status != "unverified":
            assert candidate.sampled is not None


# ------------------------------------------------------------------ what it never does


def test_every_endpoint_is_an_equation_the_paper_contains() -> None:
    """Nothing between two of the paper's lines is generated (D-028)."""
    provider = MockFullTextProvider(Path(FIXTURES_DIR))
    record = provider.fetch_source("arXiv:2601.00004")
    assert record is not None
    document = parse_document(record.body)
    present = {equation.latex for equation in document.equations}

    for candidate in candidates_for(document):
        assert candidate.from_latex in present
        assert candidate.to_latex in present


def test_a_candidate_is_labelled_as_coming_from_the_paper() -> None:
    # Both endpoints and the operation sentence are the author's, so `ai_explanation`
    # would be as wrong here as `original` would be on a generated step.
    assert all(c.provenance_kind == "original" for c in _candidates("arXiv:2601.00004"))


def test_only_consecutive_equations_are_linked() -> None:
    # A link between equation 1 and equation 7 is a claim about structure that this stage
    # has no evidence for.
    candidates = _candidates("arXiv:2601.00001")

    assert [(c.from_index, c.to_index) for c in candidates] == [(0, 1), (1, 2), (2, 3), (3, 4)]


def test_a_document_with_one_equation_produces_no_steps() -> None:
    document = parse_document(r"\begin{equation}x = 1\end{equation}")

    assert candidates_for(document) == []


# ------------------------------------------------------------------ relation labels


def test_it_reads_the_operation_off_the_authors_sentence() -> None:
    assert classify_relation("Squaring both sides gives") == "square_both_sides"
    assert classify_relation("Changing to polar coordinates, we obtain") == "change_of_variables"
    assert classify_relation("Substituting the definition yields") == "substitution"


def test_a_sentence_it_does_not_understand_gets_no_label() -> None:
    """`None` is a normal answer; a label invented for it would be a claim."""
    assert classify_relation("This is the main result of the paper.") is None


def test_a_noun_does_not_trigger_the_verb_label() -> None:
    """ "contributes a factor of 2\\pi" describes the result, not the operation.

    A cue that fires on the wrong sentence produces a confident, wrong label — which is
    exactly what a reader cannot check.
    """
    assert classify_relation("The angular integral contributes a factor of 2pi") != "factorise"
    assert classify_relation("Factorising the numerator gives") == "factorise"


def test_the_operation_text_leads_with_the_operation() -> None:
    """Papers state what they did in the sentence *before* the resulting equation.

    Leading with the previous equation's symbol definitions made the operation read as
    though the definitions were the transformation.
    """
    first = _candidates("arXiv:2601.00004")[0]

    assert first.operation.startswith("Expanding the fraction")
