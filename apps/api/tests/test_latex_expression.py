"""LaTeX to an evaluable expression (spec section 12; closes part of D-028).

The dangerous failure is not refusing too much — it is accepting something and getting it
subtly wrong, because the step then earns a verification badge for a statement nobody
made. So most of these tests assert a refusal.
"""

from __future__ import annotations

import pytest

from papermatch_api.mathcheck.verify import evaluate
from papermatch_api.text.latex_expression import translate_equation, translate_expression


def _value(latex: str, **variables: float) -> float:
    translated = translate_expression(latex)
    assert translated is not None, f"unexpectedly refused: {latex}"
    return evaluate(translated[0], variables)


# ------------------------------------------------------------------ what it accepts


@pytest.mark.parametrize(
    ("latex", "variables", "expected"),
    [
        ("2 + 3", {}, 5.0),
        ("2x", {"x": 4.0}, 8.0),
        (r"\frac{a + b}{2}", {"a": 1.0, "b": 3.0}, 2.0),
        (r"x^{2}", {"x": 3.0}, 9.0),
        (r"\sqrt{16}", {}, 4.0),
        (r"\sqrt[3]{27}", {}, 3.0),
        (r"2 \cdot 3", {}, 6.0),
        (r"\pi", {}, 3.141592653589793),
        (r"-x", {"x": 5.0}, -5.0),
        (r"\left( a + b \right) \times 2", {"a": 1.0, "b": 2.0}, 6.0),
    ],
)
def test_it_evaluates_the_arithmetic_core(
    latex: str, variables: dict[str, float], expected: float
) -> None:
    assert _value(latex, **variables) == pytest.approx(expected)


def test_a_greek_letter_is_a_variable_name() -> None:
    assert _value(r"2\beta", **{"beta": 3.0}) == pytest.approx(6.0)


def test_a_symbol_that_collides_with_a_python_keyword_is_renamed() -> None:
    r"""`\lambda` is one of the most common symbols in a paper, and a Python keyword.

    Left as `lambda`, the produced expression was a syntax error rather than a refusal —
    the caller got a crash where it expected a clean "cannot check this".
    """
    translated = translate_expression(r"2\lambda")

    assert translated is not None
    expression, variables = translated
    assert variables == {"lambda_"}
    assert evaluate(expression, {"lambda_": 3.0}) == pytest.approx(6.0)


def test_a_subscript_becomes_part_of_the_name() -> None:
    """`t_{\\mathrm{mix}}` is one variable, not `t` times something.

    Reading it as a product would sample two variables that do not exist, and they could
    agree with the other side by accident.
    """
    translated = translate_expression(r"t_{\mathrm{mix}}")

    assert translated is not None
    expression, variables = translated
    assert variables == {"t_mix"}
    assert evaluate(expression, {"t_mix": 7.0}) == pytest.approx(7.0)


def test_it_splits_an_equation_into_two_sides() -> None:
    equation = translate_equation(r"E = mc^{2}")

    assert equation is not None
    assert equation.variables == {"E", "m", "c"}
    assert evaluate(equation.rhs, {"m": 2.0, "c": 3.0}) == pytest.approx(18.0)


def test_it_reports_which_variable_an_equation_defines() -> None:
    equation = translate_equation(r"y = \frac{a + b}{2}")

    assert equation is not None
    assert equation.defines == "y"


def test_an_equation_with_no_isolated_variable_defines_nothing() -> None:
    # `2y = a + b` constrains y but does not solve for it, and a substitution check needs
    # the solved form.
    equation = translate_equation(r"2 y = a + b")

    assert equation is not None
    assert equation.defines is None


def test_a_variable_appearing_on_both_sides_is_not_a_definition() -> None:
    equation = translate_equation(r"x = x + 1")

    assert equation is not None
    assert equation.defines is None


# ------------------------------------------------------------------ what it refuses


@pytest.mark.parametrize(
    "latex",
    [
        r"\int_{0}^{1} f \, dx",
        r"\sum_{n=1}^{10} n",
        r"\prod_{i} a_i",
        r"\lim_{x \to 0} f",
        r"\frac{\partial f}{\partial x}",
        r"\begin{pmatrix} a \\ b \end{pmatrix}",
        r"\binom{n}{k}",
    ],
)
def test_it_refuses_constructs_it_cannot_evaluate(latex: str) -> None:
    """Dropping `\\int` silently would turn an integral identity into an arithmetic one.

    It would then sample, pass, and hand the formula a verification badge earned by a
    different statement.
    """
    assert translate_expression(latex) is None


def test_it_refuses_an_unknown_command_rather_than_ignoring_it() -> None:
    assert translate_expression(r"\erf{x}") is None


def test_it_refuses_an_identifier_followed_by_a_bracket() -> None:
    """`I(a)` is function application in a paper and a product in LaTeX's grammar.

    Nothing in the markup says which. Reading it as `I * a` produced a wrong expression
    *silently*, which is the one outcome this module exists to prevent.
    """
    assert translate_equation(r"I(a) = \sqrt{\frac{\pi}{a}}") is None
    assert translate_expression(r"\lambda(t)") is None


def test_a_number_followed_by_a_bracket_is_still_multiplication() -> None:
    # Unambiguous: a number cannot be a function.
    assert _value("2(x + 1)", x=3.0) == pytest.approx(8.0)


def test_it_refuses_a_chained_equality() -> None:
    """`a = b = c` is two claims, and picking one silently checks something else."""
    assert translate_equation(r"a = b = c") is None


def test_it_refuses_an_expression_with_no_equals_sign() -> None:
    assert translate_equation(r"x + 1") is None


def test_it_refuses_unbalanced_braces() -> None:
    assert translate_expression(r"\frac{a}{") is None


def test_it_refuses_a_stray_closing_bracket() -> None:
    assert translate_expression(r"a + b)") is None


def test_it_refuses_an_empty_expression() -> None:
    assert translate_expression("") is None


def test_it_refuses_characters_outside_the_grammar() -> None:
    assert translate_expression(r"a \# b") is None
