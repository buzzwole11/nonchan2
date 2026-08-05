"""Declared units → base dimensions (spec section 12: 次元解析).

The dimensional check raises a step's `verificationStatus`, and `mechanically_verified` is
a label a reader is entitled to trust. So the tests that matter are the ones that check a
unit is *refused* rather than guessed, and that "we could not tell" never quietly becomes
"we checked and it is fine".
"""

from __future__ import annotations

import pytest

from papermatch_api.mathcheck.units import (
    DimensionError,
    dimension_of_expression,
    parse_dimensions,
    parse_unit,
)
from papermatch_api.services.derivation import units_from_symbols

# ------------------------------------------------------------------ reading a unit


def test_an_si_base_unit_is_its_own_dimension() -> None:
    assert parse_unit("m") == {"L": 1}
    assert parse_unit("s") == {"T": 1}


def test_a_derived_unit_expands_to_bases() -> None:
    assert parse_unit("J") == {"M": 1, "L": 2, "T": -2}


def test_a_quotient_with_an_exponent() -> None:
    assert parse_unit("m/s^2") == {"L": 1, "T": -2}


def test_a_product_in_either_notation() -> None:
    assert parse_unit("kg m/s^2") == parse_unit("kg*m/s^2") == {"M": 1, "L": 1, "T": -2}


def test_dimensionless_is_a_declaration_not_an_absence() -> None:
    # `{}` means "this has no dimensions", which is a fact. `None` means "nobody said",
    # which is not. The two must not collapse into each other.
    assert parse_unit("1") == {}
    assert parse_unit("無次元") == {}
    assert parse_unit(None) is None
    assert parse_unit("") is None


@pytest.mark.parametrize(
    "unit",
    [
        "arb. units",
        "a.u.",
        "dimensionless (see text)",
        "km",  # a prefix we do not handle; reading it as metres would be wrong by 1000
        "m/s/s",  # two solidi: ambiguous, and papers write both meanings
        "furlong",
    ],
)
def test_a_unit_that_cannot_be_read_confidently_is_refused(unit: str) -> None:
    # Refusing costs a check that would not have run. Guessing costs a wrong verdict on a
    # label the reader trusts.
    assert parse_unit(unit) is None


# ------------------------------------------------------------------ an expression's dimension


def test_an_expression_takes_its_dimension_from_its_variables() -> None:
    units = {"a": {"L": 1, "T": -2}, "t": {"T": 1}}

    assert dimension_of_expression("a * t**2", units) == {"L": 1}


def test_a_bare_number_is_dimensionless() -> None:
    assert dimension_of_expression("2", {}) == {}


def test_an_undeclared_variable_makes_the_answer_unknown() -> None:
    # Not dimensionless. Treating an unknown as dimensionless is precisely the assumption
    # that turns a missing declaration into a confident wrong verdict.
    assert dimension_of_expression("x * 2", {}) is None
    assert dimension_of_expression("a + x", {"a": {"L": 1}}) is None


def test_adding_unlike_dimensions_is_a_finding_not_a_refusal() -> None:
    # `t + x` in seconds and metres is wrong, and saying "cannot tell" would let it through.
    with pytest.raises(DimensionError, match="cannot add"):
        dimension_of_expression("t + x", {"t": {"T": 1}, "x": {"L": 1}})


def test_a_logarithm_of_a_dimensional_quantity_is_a_finding() -> None:
    with pytest.raises(DimensionError, match="log"):
        dimension_of_expression("log(t)", {"t": {"T": 1}})


def test_a_logarithm_of_a_ratio_is_fine() -> None:
    assert dimension_of_expression("log(t / t0)", {"t": {"T": 1}, "t0": {"T": 1}}) == {}


def test_a_square_root_halves_the_exponents() -> None:
    assert dimension_of_expression("sqrt(x)", {"x": {"L": 2}}) == {"L": 1}


def test_a_square_root_that_does_not_divide_evenly_is_a_finding() -> None:
    with pytest.raises(DimensionError, match="square root"):
        dimension_of_expression("sqrt(x)", {"x": {"L": 1}})


def test_a_non_literal_exponent_makes_the_answer_unknown() -> None:
    # `x**y` has no dimension unless `y` is a known number, and rounding a fractional
    # exponent would be inventing one.
    assert dimension_of_expression("x**y", {"x": {"L": 1}, "y": {}}) is None


# ------------------------------------------------------------------ from a symbol table


def test_symbols_with_readable_units_become_dimensions() -> None:
    assert units_from_symbols({"t": "s", "x": "m"}) == {"t": {"T": 1}, "x": {"L": 1}}


def test_a_symbol_with_no_unit_is_dropped_rather_than_defaulted() -> None:
    # And the check then declines to run for any expression mentioning it, which is the
    # correct outcome: nobody said what it is.
    units = units_from_symbols({"t": "s", "c": None, "k": "arb. units"})

    assert set(units) == {"t"}
    assert dimension_of_expression("t * c", units) is None


# ------------------------------------------------------------------ the other notation


def test_base_dimension_notation_is_read_by_its_own_parser() -> None:
    assert parse_dimensions("M L / T") == {"M": 1, "L": 1, "T": -1}
    assert parse_dimensions("1/L^2") == {"L": -2}
    assert parse_dimensions("I^2 T^3 / (M L^2)") == {"I": 2, "T": 3, "M": -1, "L": -2}


def test_the_two_notations_disagree_about_T_and_that_is_why_they_are_separate() -> None:
    # `T` is tesla as a unit and time as a base dimension. Nothing in the string says which,
    # so auto-detecting would silently turn a duration into a magnetic field. The caller
    # picks, because the caller knows what its own corpus writes.
    assert parse_unit("T") == {"M": 1, "T": -2, "I": -1}
    assert parse_dimensions("T") == {"T": 1}


def test_an_si_unit_is_not_valid_base_dimension_notation() -> None:
    assert parse_dimensions("m/s^2") is None


def test_the_notation_is_chosen_by_the_caller() -> None:
    assert units_from_symbols({"t": "T"}, notation="dimensions") == {"t": {"T": 1}}
    assert units_from_symbols({"b": "T"}) == {"b": {"M": 1, "T": -2, "I": -1}}


def test_a_literal_zero_takes_the_dimension_of_what_it_is_added_to() -> None:
    # `0 - E` is how a difference is written. Treating the zero as dimensionless like any
    # other number reported the fixtures' own correct expressions as inconsistent.
    assert dimension_of_expression("0 - x", {"x": {"L": 1}}) == {"L": 1}
    assert dimension_of_expression("x - 0", {"x": {"L": 1}}) == {"L": 1}


def test_a_non_zero_number_added_to_a_dimensional_quantity_is_still_a_finding() -> None:
    with pytest.raises(DimensionError, match="cannot add"):
        dimension_of_expression("x + 2", {"x": {"L": 1}})
