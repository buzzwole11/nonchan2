"""Hand-authored maths cards, and the checks that decide what they claim.

Spec Phase 4 asks for 手動作成した検証済み数式カード. The tests that matter here are the ones
that keep "検証済み" from being a word someone typed: the statuses have to come out of a
check, the check has to be capable of failing, and a step that passed nothing has to
disappear from the default view.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import DerivationStep, Equation, EquationSymbol, MathCard
from papermatch_api.services.equations import (
    DEFAULT_VISIBLE_STATUSES,
    derivation_steps_for,
    is_default_visible,
    renderable,
    symbols_for,
    visible_equations,
)
from papermatch_api.services.math_content import load_math_cards, status_for_step, units_in
from papermatch_api.text.latex_safety import check_latex
from tests.conftest import FIXTURES_DIR, requires_db

DOCUMENT: dict[str, Any] = json.loads(
    (Path(FIXTURES_DIR) / "math-cards.json").read_text(encoding="utf-8")
)
CARDS: list[dict[str, Any]] = DOCUMENT["cards"]


def _card(key: str) -> dict[str, Any]:
    return next(card for card in CARDS if card["key"] == key)


STEPS: list[tuple[str, dict[str, Any]]] = [
    (f"{card['key']}:{step['operation'][:20]}", step)
    for card in CARDS
    for step in card.get("steps", [])
]


# ------------------------------------------------------------- the corpus is well formed


def test_every_formula_in_the_corpus_would_be_admitted_for_rendering() -> None:
    """A fixture formula the renderer must refuse would be a broken card, not a test."""
    for card in CARDS:
        for equation in card["equations"]:
            verdict = check_latex(equation["latex"])
            assert verdict.safe, f"{card['key']}/{equation['key']}: {verdict.issues}"


def test_every_step_formula_would_be_admitted_too() -> None:
    for key, step in STEPS:
        verdict = check_latex(step["latex"])
        assert verdict.safe, f"{key}: {verdict.issues}"


def test_the_fixture_declares_no_verification_statuses() -> None:
    """The whole point: a status is produced by running a check, never written down.

    If a status could be typed into the fixture, "verified" would mean "someone claimed
    it", which is exactly the thing spec section 12 is trying to avoid.
    """
    raw = (Path(FIXTURES_DIR) / "math-cards.json").read_text(encoding="utf-8")
    for status in ("mechanically_verified", "dimensionally_checked", "numerically_spot_checked"):
        # It may be *described* in $meta prose, but never used as a field value.
        assert f'"{status}"' not in raw.split('"cards"', 1)[1]


# ------------------------------------------------------- the checks can actually fail


@pytest.mark.parametrize(("key", "step"), STEPS, ids=[k for k, _ in STEPS])
def test_each_declared_check_has_discriminating_power(key: str, step: dict[str, Any]) -> None:
    """Perturb the step and confirm the check notices.

    A check that passes no matter what is worse than no check: it produces a verified
    status without doing any work. This mutates one side of every declared identity and
    asserts the status drops.
    """
    if "numericCheck" not in step:
        pytest.skip("no numeric check declared")

    broken = copy.deepcopy(step)
    # A multiplicative perturbation, so it survives whatever scale the expression is on.
    broken["numericCheck"]["rhs"] = f"({step['numericCheck']['rhs']}) * 1.05 + 0.01"
    status, evidence = status_for_step(broken)

    assert evidence["numeric"]["passed"] is False, f"{key}: perturbed identity still passed"
    assert status != "mechanically_verified"


@pytest.mark.parametrize(("key", "step"), STEPS, ids=[k for k, _ in STEPS])
def test_each_declared_dimension_check_has_discriminating_power(
    key: str, step: dict[str, Any]
) -> None:
    if "dimensionCheck" not in step:
        pytest.skip("no dimension check declared")

    broken = copy.deepcopy(step)
    lhs = dict(broken["dimensionCheck"]["lhs"])
    lhs["T"] = lhs.get("T", 0) + 1
    broken["dimensionCheck"]["lhs"] = lhs

    _, evidence = status_for_step(broken)
    assert evidence["dimensional"]["passed"] is False, f"{key}: perturbed dimensions still passed"


def test_no_declared_check_is_a_restatement_of_itself() -> None:
    """A check whose two sides say the same thing passes whatever the step claims.

    The mutation tests above cannot catch this — perturbing a tautology still breaks it —
    so it needs its own guard. It is a real temptation: writing `A` against `A` rearranged
    is the easiest way to make a step come out `mechanically_verified` without checking
    anything, and one step in this corpus was written that way before this test existed.
    """
    for key, step in STEPS:
        check = step.get("numericCheck")
        if check is None:
            continue
        normalise = lambda e: "".join(e.split())  # noqa: E731
        assert normalise(check["lhs"]) != normalise(check["rhs"]), f"{key}: vacuous check"


def test_the_statuses_the_corpus_produces_are_the_expected_spread() -> None:
    """Not every step earns the same thing, and that is the point.

    One card declares no check at all, so the corpus exercises the default-hidden branch
    with real data rather than only in a unit test.
    """
    produced = {status_for_step(step)[0] for _, step in STEPS}
    assert "mechanically_verified" in produced
    assert "dimensionally_checked" in produced
    assert "unverified" in produced


def test_the_evidence_records_the_region_the_identity_was_checked_on() -> None:
    """Sampling proves an identity *here*. Recording where stops a later reader
    over-reading the pass."""
    step = next(s for _, s in STEPS if "numericCheck" in s)
    _, evidence = status_for_step(step)
    assert "variables" in evidence["numeric"]
    assert evidence["numeric"]["evaluated"] > 0


# ------------------------------------------------------------------------ loading


@requires_db
def test_loading_produces_cards_equations_symbols_and_steps(seeded_db: Session) -> None:
    report = load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()

    assert report.cards == len(CARDS)
    assert report.rejected_equations == []
    assert report.missing_papers == [], "a card names a paper the corpus does not contain"
    assert report.equations > 0 and report.symbols > 0 and report.steps > 0


@requires_db
def test_a_stored_step_carries_the_evidence_for_its_status(seeded_db: Session) -> None:
    """A status with no record of how it was reached is barely better than an assertion."""
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()

    step = (
        seeded_db.execute(
            select(DerivationStep).where(
                DerivationStep.verification_status == "mechanically_verified"
            )
        )
        .scalars()
        .first()
    )
    assert step is not None
    assert step.generation is not None
    assert step.generation["numeric"]["passed"] is True
    assert step.generation["dimensional"]["passed"] is True


@requires_db
def test_an_unverified_step_is_stored_but_not_shown(seeded_db: Session) -> None:
    """Spec section 12: 未検証の変形は既定で非表示.

    Stored, because the review queue needs it. Not returned, because a reader cannot tell
    an unchecked transformation from a checked one by looking at it.
    """
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()

    unverified = (
        seeded_db.execute(
            select(DerivationStep).where(DerivationStep.verification_status == "unverified")
        )
        .scalars()
        .all()
    )
    assert unverified, "the corpus should contain one deliberately unverified step"

    equation_ids = [s.from_equation_id for s in unverified] + [s.to_equation_id for s in unverified]
    assert derivation_steps_for(seeded_db, equation_ids) == []
    assert len(derivation_steps_for(seeded_db, equation_ids, include_unverified=True)) == len(
        unverified
    )


@requires_db
def test_an_unverified_step_is_labelled_an_explanation_not_a_verified_step(
    seeded_db: Session,
) -> None:
    """Spec section 11's provenance labels. A step that passed no check is not a
    `verified_step`, and calling it one would be the exact overstatement the vocabulary
    exists to prevent."""
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()

    for step in seeded_db.execute(select(DerivationStep)).scalars():
        if step.verification_status == "unverified":
            assert step.provenance_kind == "ai_explanation"
        else:
            assert step.provenance_kind == "verified_step"


@requires_db
def test_nothing_claims_to_have_been_reviewed_by_a_human(seeded_db: Session) -> None:
    """No human has reviewed this corpus, so nothing in it may say so."""
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()

    for model in (Equation, DerivationStep):
        rows = seeded_db.execute(select(model)).scalars().all()
        assert all(r.verification_status != "human_reviewed" for r in rows)
        assert all(r.provenance_kind != "human_reviewed" for r in rows)
    cards = seeded_db.execute(select(MathCard)).scalars().all()
    assert all(c.review_status == "draft" for c in cards)


@requires_db
def test_symbol_meanings_are_labelled_as_written_prose(seeded_db: Session) -> None:
    """The formula is the paper's; the sentence explaining a symbol is not."""
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()

    symbols = seeded_db.execute(select(EquationSymbol)).scalars().all()
    assert symbols
    assert all(s.provenance_kind == "ai_explanation" for s in symbols)


@requires_db
def test_loading_twice_does_not_duplicate_the_corpus(seeded_db: Session) -> None:
    """`make seed` is documented as safe to re-run."""
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()
    first = len(seeded_db.execute(select(Equation)).scalars().all())

    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()
    second = len(seeded_db.execute(select(Equation)).scalars().all())

    assert first == second


@requires_db
def test_symbols_come_back_for_an_equation_that_has_them(seeded_db: Session) -> None:
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()

    equation = (
        seeded_db.execute(select(Equation).where(Equation.latex.like("%e^{-a x^{2}}%")))
        .scalars()
        .first()
    )
    assert equation is not None
    names = [s.symbol for s in symbols_for(seeded_db, equation.id)]
    assert names == sorted(names), "a stable order is easier to scan than insertion order"
    assert "a" in names and "x" in names


@requires_db
def test_equations_for_a_paper_exclude_nothing_when_all_are_source_exact(
    seeded_db: Session,
) -> None:
    load_math_cards(seeded_db, FIXTURES_DIR)
    seeded_db.flush()

    equation = seeded_db.execute(select(Equation)).scalars().first()
    assert equation is not None
    found = visible_equations(seeded_db, equation.paper_id)
    assert equation.id in {e.id for e in found}


# ------------------------------------------------------------------ rendering verdict


def test_a_renderable_equation_reports_itself_as_such() -> None:
    result = renderable(r"E = mc^2")
    assert result.renderable is True
    assert result.refusal_reasons == ()


def test_a_refused_equation_still_travels_with_its_source() -> None:
    """Spec section 11's fallback is the LaTeX source and a link to the paper, not a gap.

    The client needs the string in order to show it, so refusing to render is not the same
    as refusing to send.
    """
    result = renderable(r"\href{javascript:1}{x}")
    assert result.renderable is False
    assert result.latex == r"\href{javascript:1}{x}"
    assert "forbidden_command" in result.refusal_reasons


def test_the_visible_set_is_every_status_except_unverified() -> None:
    assert is_default_visible("source_exact")
    assert is_default_visible("human_reviewed")
    assert not is_default_visible("unverified")
    assert "unverified" not in DEFAULT_VISIBLE_STATUSES


# ------------------------------------------------------------------ dimensions from symbols


def test_units_are_read_from_the_symbol_table_rather_than_written_out_again() -> None:
    """Section 12's 次元解析, fed from the symbols the card already carries.

    The fixtures declare a `dimensionCheck` per step, which is the same fact written a
    second time. Two hand-written copies drift, and the one that drifts is the one nobody
    looks at — so when a step has no explicit check, the units on its symbols supply one.
    """
    entry = _card("gaussian-integral")
    units = units_in(entry)

    assert units["a"] == {"L": -2}
    assert units["r"] == {"L": 1}


def test_a_step_with_no_declared_dimension_check_gets_one_from_the_symbols() -> None:
    entry = _card("relativistic-limit")
    step = next(s for s in entry["steps"] if s.get("numericCheck"))
    without = {key: value for key, value in step.items() if key != "dimensionCheck"}

    status, evidence = status_for_step(without, units_in(entry))

    assert status == "mechanically_verified"
    assert evidence["dimensional"]["source"] == "symbol_table"


def test_a_step_whose_variables_are_not_all_declared_gets_no_dimensional_verdict() -> None:
    # The polar-coordinates step samples an angle, which has no unit in the table. Refusing
    # is right: a verdict computed from a guessed unit would raise the step's status on
    # evidence that does not exist.
    entry = _card("gaussian-integral")
    step = next(s for s in entry["steps"] if s["to"] == "gauss-polar")
    without = {key: value for key, value in step.items() if key != "dimensionCheck"}

    status, evidence = status_for_step(without, units_in(entry))

    assert status == "numerically_spot_checked"
    assert "dimensional" not in evidence
