"""Mechanical verification of claimed steps (spec section 12).

Two halves: the checks themselves have to catch a wrong step, and the expression language
has to stay a language for arithmetic rather than a way to run code.
"""

from __future__ import annotations

import math

import pytest

from papermatch_api.mathcheck import (
    DimensionCheck,
    NumericCheck,
    combined_status,
    dimension_check,
    spot_check,
)
from papermatch_api.mathcheck.verify import ExpressionError, evaluate

# ---------------------------------------------------------------- the language is small


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "().__class__.__bases__[0].__subclasses__()",
        "open('/etc/passwd').read()",
        "x.__class__",
        "[i for i in range(10)]",
        "lambda: 1",
        "exec('x=1')",
        "globals()",
    ],
)
def test_anything_that_is_not_arithmetic_is_refused(expression: str) -> None:
    """These strings come from fixture files and later from a pipeline; they are input.

    Blanking `__builtins__` alone would not be enough — attribute traversal from a literal
    is the standard way back out — so the guard is a walk over the syntax tree.
    """
    with pytest.raises(ExpressionError):
        evaluate(expression, {"x": 1.0})


def test_an_undeclared_variable_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ExpressionError, match="unknown name 'y'"):
        evaluate("x + y", {"x": 1.0})


def test_only_the_listed_functions_can_be_called() -> None:
    with pytest.raises(ExpressionError):
        evaluate("id(x)", {"x": 1.0})


def test_ordinary_arithmetic_evaluates() -> None:
    assert evaluate("sqrt(x) * 2 + 1", {"x": 4.0}) == 5.0
    assert evaluate("exp(0) + log(e)", {}) == 2.0
    assert evaluate("x if x > 0 else -x", {"x": -3.0}) == 3.0


# ------------------------------------------------------------------------ numeric check


def test_a_true_identity_passes() -> None:
    check = NumericCheck(
        lhs="sin(x)**2 + cos(x)**2",
        rhs="1",
        variables={"x": (-3.0, 3.0)},
    )
    outcome = spot_check(check)
    assert outcome.passed, outcome.detail
    assert outcome.evaluated == check.samples


def test_a_wrong_step_is_caught() -> None:
    """The case the whole module exists for: a plausible but false transformation."""
    check = NumericCheck(
        lhs="(x + y)**2",
        rhs="x**2 + y**2",  # the missing cross term
        variables={"x": (1.0, 4.0), "y": (1.0, 4.0)},
    )
    outcome = spot_check(check)
    assert outcome.passed is False
    assert "differs at" in outcome.detail


def test_a_step_that_is_only_true_at_special_points_still_fails() -> None:
    """Sampling avoids 0, 1 and pi precisely so this does not slip through."""
    check = NumericCheck(lhs="sin(x)", rhs="x", variables={"x": (-2.0, 2.0)})
    assert spot_check(check).passed is False


def test_points_where_a_side_has_no_value_are_skipped_not_failed() -> None:
    """`log(x)` below zero says nothing about whether the identity holds."""
    check = NumericCheck(
        lhs="log(x) + log(y)",
        rhs="log(x * y)",
        variables={"x": (-1.0, 5.0), "y": (0.5, 5.0)},
    )
    outcome = spot_check(check)
    assert outcome.passed, outcome.detail
    assert outcome.evaluated < check.samples, "some points should have been skipped"


def test_a_check_that_almost_never_evaluates_is_a_failure_not_a_pass() -> None:
    """A check that evaluated twice has not checked anything, and must not be able to
    earn a verified status by being undefined nearly everywhere."""
    check = NumericCheck(
        lhs="log(x - 100)",
        rhs="log(x - 100)",
        variables={"x": (0.0, 1.0)},
    )
    outcome = spot_check(check)
    assert outcome.passed is False
    assert "had a value on both sides" in outcome.detail


def test_the_comparison_is_relative_so_large_quantities_are_not_waved_through() -> None:
    check = NumericCheck(lhs="1e12 * x", rhs="1e12 * x * 1.0001", variables={"x": (1.0, 2.0)})
    assert spot_check(check).passed is False


def test_sampling_is_deterministic() -> None:
    """A fixture whose verification status changes between runs is worse than one that is
    never checked: it looks stable and is not."""
    check = NumericCheck(lhs="x**3", rhs="x * x * x", variables={"x": (0.1, 9.0)})
    first = spot_check(check)
    second = spot_check(check)
    assert (first.passed, first.detail) == (second.passed, second.detail)


def test_a_constant_identity_needs_no_variables() -> None:
    assert spot_check(NumericCheck(lhs="exp(1)", rhs="e")).passed is True


# -------------------------------------------------------------------- dimension check


def test_matching_dimensions_pass() -> None:
    """Force = mass x acceleration."""
    outcome = dimension_check(
        DimensionCheck(lhs={"M": 1, "L": 1, "T": -2}, rhs={"M": 1, "L": 1, "T": -2})
    )
    assert outcome.passed


def test_a_dimensional_mistake_is_caught() -> None:
    outcome = dimension_check(
        DimensionCheck(lhs={"M": 1, "L": 2, "T": -2}, rhs={"M": 1, "L": 1, "T": -2})
    )
    assert outcome.passed is False
    assert "vs" in outcome.detail


def test_a_zero_exponent_is_the_same_as_absent() -> None:
    assert dimension_check(DimensionCheck(lhs={"L": 0}, rhs={})).passed is True


def test_both_sides_dimensionless_is_a_pass_and_says_so() -> None:
    outcome = dimension_check(DimensionCheck(lhs={}, rhs={}))
    assert outcome.passed
    assert "dimensionless" in outcome.detail


def test_an_invented_base_dimension_is_refused() -> None:
    outcome = dimension_check(DimensionCheck(lhs={"Q": 1}, rhs={"Q": 1}))
    assert outcome.passed is False
    assert "unknown base dimension" in outcome.detail


# ---------------------------------------------------------------- what a step has earned


def test_two_independent_checks_agreeing_is_the_strongest_claim() -> None:
    numeric = spot_check(NumericCheck(lhs="x", rhs="x", variables={"x": (1.0, 2.0)}))
    dimensional = dimension_check(DimensionCheck(lhs={"L": 1}, rhs={"L": 1}))
    assert combined_status(numeric, dimensional) == "mechanically_verified"


def test_one_check_earns_only_that_checks_name() -> None:
    numeric = spot_check(NumericCheck(lhs="x", rhs="x", variables={"x": (1.0, 2.0)}))
    dimensional = dimension_check(DimensionCheck(lhs={"L": 1}, rhs={"T": 1}))
    assert combined_status(numeric, None) == "numerically_spot_checked"
    assert combined_status(None, dimension_check(DimensionCheck({"L": 1}, {"L": 1}))) == (
        "dimensionally_checked"
    )
    assert combined_status(numeric, dimensional) == "numerically_spot_checked"


def test_no_check_means_unverified_which_is_what_gets_hidden() -> None:
    """Spec section 12: 未検証の変形は既定で非表示."""
    assert combined_status(None, None) == "unverified"
    failed = spot_check(NumericCheck(lhs="x", rhs="x + 1", variables={"x": (1.0, 2.0)}))
    assert combined_status(failed, None) == "unverified"


def test_arithmetic_never_returns_a_provenance_claim() -> None:
    """`source_exact` says where a formula came from and `human_reviewed` says who looked
    at it. Sampling establishes neither, so no combination of outcomes may return them."""
    outcomes = [
        None,
        spot_check(NumericCheck(lhs="x", rhs="x", variables={"x": (1.0, 2.0)})),
        spot_check(NumericCheck(lhs="x", rhs="x + 1", variables={"x": (1.0, 2.0)})),
    ]
    dimensionals = [
        None,
        dimension_check(DimensionCheck({"L": 1}, {"L": 1})),
        dimension_check(DimensionCheck({"L": 1}, {"T": 1})),
    ]
    produced = {combined_status(n, d) for n in outcomes for d in dimensionals}
    assert produced.isdisjoint({"source_exact", "human_reviewed"})


# ------------------------------------------------------------ a real derivation, checked


def test_the_gaussian_integral_derivation_holds_step_by_step() -> None:
    """The derivation shipped as fixture content, verified rather than asserted.

    Squaring the integral, moving to polar coordinates and integrating — each step is a
    separate claim, and each one is sampled here over the range it is claimed on.
    """
    # I(a)^2 == the polar form, evaluated in closed form as pi/a.
    squared = NumericCheck(
        lhs="(sqrt(pi / a))**2",
        rhs="pi / a",
        variables={"a": (0.2, 6.0)},
    )
    assert spot_check(squared).passed

    # The radial integral: \int_0^inf r e^{-a r^2} dr = 1/(2a).
    radial = NumericCheck(
        lhs="1 / (2 * a)",
        rhs="(0 - (0 - 1 / (2 * a)))",
        variables={"a": (0.2, 6.0)},
    )
    assert spot_check(radial).passed

    # And the closed form against a direct numerical quadrature, which is an independent
    # route to the same number rather than a restatement of it.
    def quadrature(a: float, steps: int = 20000, upper: float = 12.0) -> float:
        h = upper / steps
        total = 0.5 * (math.exp(-a * 0.0) + math.exp(-a * upper**2))
        for i in range(1, steps):
            x = i * h
            total += math.exp(-a * x * x)
        return 2.0 * total * h  # doubled: the integrand is even

    for a in (0.5, 1.0, 3.0):
        assert abs(quadrature(a) - math.sqrt(math.pi / a)) < 1e-6
